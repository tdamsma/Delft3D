!----- AGPL --------------------------------------------------------------------
!
!  Copyright (C)  Stichting Deltares, 2017-2026.
!
!  This file is part of Delft3D (D-Flow Flexible Mesh component).
!
!  Delft3D is free software: you can redistribute it and/or modify
!  it under the terms of the GNU Affero General Public License as
!  published by the Free Software Foundation version 3.
!
!  Delft3D  is distributed in the hope that it will be useful,
!  but WITHOUT ANY WARRANTY; without even the implied warranty of
!  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
!  GNU Affero General Public License for more details.
!
!  You should have received a copy of the GNU Affero General Public License
!  along with Delft3D.  If not, see <http://www.gnu.org/licenses/>.
!
!  contact: delft3d.support@deltares.nl
!  Stichting Deltares
!  P.O. Box 177
!  2600 MH Delft, The Netherlands
!
!  All indications and logos of, and references to, "Delft3D",
!  "D-Flow Flexible Mesh" and "Deltares" are registered trademarks of Stichting
!  Deltares, and remain the property of Stichting Deltares. All rights reserved.
!
!-------------------------------------------------------------------------------
module m_setuc1d

   implicit none

   private

   public :: setuc1d

contains

   !> @brief Set representative velocities for 1D flow elements
   !> 
   !> This subroutine computes representative velocities at 1D flow network nodes
   !> for use in advection schemes and momentum transport calculations. It handles
   !> different computational modes based on jaPure1D settings:
   !> - Basic mode: Computes nodal velocities (uc1D) from momentum conservation
   !> - Upwind mode (jaPure1D=1,2): Adds upwind velocity assignment on links
   !> - Advanced mode (jaPure1D>=3): Includes storage effects and correction factors
   !>
   !> @details The algorithm:
   !> 1. Identifies valid 1D nodes (all connected links must be 1D type)
   !> 2. Computes momentum-weighted average velocities at nodes
   !> 3. Handles special boundary conditions
   !> 4. Optionally computes upwind velocities and storage-corrected parameters
   subroutine setuc1d()
      use m_netw
      use m_flow
      use m_flowgeom
      use m_get_prof_1D
      use precision, only: dp
      implicit none

      integer, parameter :: JACSTOT = 0 !< 0 for computing the total area
      integer, parameter :: JACSFLW = 1 !< 1 for computing the flow area
      integer, parameter :: CALCCONV = 0 !< don't update wu, cfuhi, etc inside getprof_1D

      integer :: L, LL, La, n, nx, ja1D

      real(kind=dp) :: q_net_in !< [m3/s] sum of inflowing Q minus sum of outflowing Q over links of node n
      real(kind=dp) :: q_in !< [m3/s] sum of inflowing Q over links of node n
      real(kind=dp) :: q_out !< [m3/s] sum of outflowing Q over links of node n
      real(kind=dp) :: qu_in !< [m4/s2] sum of Q*u over inflowing links of node n
      real(kind=dp) :: qu_out !< [m4/s2] sum of Q*u over outflowing links of node n (u = Q/A)
      real(kind=dp) :: qu2_in !< [m5/s3] sum of Q*u**2 over inflowing links of node n
      real(kind=dp) :: qu2_out !< [m5/s3] sum of Q*u**2 over outflowing links of node n (u = Q/A)
      real(kind=dp) :: uc !< [m/s] representative velocity magnitude at node n

      integer :: L1 !< index of first link
      integer :: k !< node index: 1 for link start node, and 2 for link end node
      real(kind=dp) :: h !< [m] local water depth
      real(kind=dp) :: half_link_length !< [m] half link length
      real(kind=dp) :: u !< [m/s] velocity
      real(kind=dp) :: q !< [m3/s] discharge
      real(kind=dp) :: perim !< [m] dummy variable for wetted perimeter
      real(kind=dp) :: flow_cs_area !< [m2] cross-sectional flow area
      real(kind=dp) :: total_cs_area !< [m2] cross-sectional total (flow + storage) area
      real(kind=dp) :: link_surface_area !< [m2] surface area of half link
      real(kind=dp) :: surface_area !< [m2] total surface area of node -- equal to a1(n)
      real(kind=dp) :: flow_width !< [m] surface width of flow area
      real(kind=dp) :: total_width !< [m] surface width of total (flow + storage) area
      real(kind=dp) :: dzw_dt !< [m/s] water level change rate

      ! ======================================================================
      ! Early return if not applicable:
      ! - kmx /= 0: 3D simulation (sigma layers active)
      ! - lnx1D == 0: no 1D links in the model
      ! ======================================================================
      if (kmx /= 0 .or. lnx1D == 0) then
         return
      end if

      if (japure1d==1 .or. japure1d==2) then
      ! ======================================================================
      ! STAGE 1: Compute representative velocities at 1D nodes (uc1D)
      ! ======================================================================
      uc1D = 0.0_dp
      
      ! Loop through all 1D nodes (beyond the 2D domain)
      do n = ndx2D + 1, ndxi
         nx = nd(n)%lnx  ! number of links connected to this node

         ! Check if this is a valid 1D node (all connected links must be 1D)
         ja1D = 1
         do LL = 1, nx
            L = nd(n)%ln(LL)   ! link number (signed: +/- indicates direction)
            La = abs(L)        ! absolute link number
            if (abs(kcu(La)) /= 1) then  ! kcu = ±1 for 1D flow types
               ja1D = 0        ! not a pure 1D node
            end if
         end do
         if (ja1D == 0) then
            cycle  ! skip non-1D nodes
         end if
         
         ! Skip junctions if not enabled (only process simple channel nodes)
         if (jaJunction1D == 0 .and. nx > 2) then
            cycle  ! skip nodes with more than 2 links when junctions disabled
         end if

         ! Initialize momentum and discharge sums
         qu_in = 0.0_dp   ! momentum flux into node [m⁴/s²]
         qu_out = 0.0_dp  ! momentum flux out of node [m⁴/s²]
         q_in = 0.0_dp    ! total discharge into node [m³/s]
         q_out = 0.0_dp   ! total discharge out of node [m³/s]
         
         ! Analyze flow directions and compute momentum fluxes
         do LL = 1, nx ! loop over all links connected to the node
            L = nd(n)%ln(LL)   ! link number: positive if points TO node, negative if points FROM node
            La = abs(L)        ! absolute link number

            ! Determine flow direction relative to node:
            ! L*u1(La) >= 0: flow INTO node (inflow)
            ! L*u1(La) < 0:  flow OUT OF node (outflow)
            if (L * u1(La) >= 0.0_dp) then 
               ! INFLOW: accumulate momentum and discharge
                  qu_in = qu_in + qa(La) * u1(La)   ! momentum flux = Q * u
                  q_in = q_in + abs(qa(La))          ! total inflow discharge
               else 
                  ! OUTFLOW: accumulate momentum and discharge
                  qu_out = qu_out + qa(La) * u1(La) ! momentum flux = Q * u
                  q_out = q_out + abs(qa(La))        ! total outflow discharge
               end if
            end do

            ! Compute representative velocity magnitude from momentum conservation
            if (q_in > 0.0_dp .and. q_out > 0.0_dp) then
               ! Mixed flow: average of momentum-weighted velocities
               ! uc = 0.5 * (u_inflow_avg + u_outflow_avg)
               uc = 0.5_dp * (qu_in / q_in + qu_out / q_out)
            else 
               ! Single-direction flow or stagnant: no characteristic velocity
               uc = 0.0_dp
            end if

            ! Assign velocity with appropriate sign based on first link direction
            L1 = abs(nd(n)%ln(1))          ! reference link for sign
            uc1D(n) = sign(uc, u1(L1))      ! apply sign from reference link
         end do

         ! ======================================================================
         ! Handle 1D boundary nodes (special case)
         ! ======================================================================
         do LL = lnxi + 1, lnx ! loop over open boundary links
            if (kcu(LL) == -1) then ! 1D boundary link identifier
               n = Ln(1, LL)       ! boundary node

               ! Boundary nodes have only one link (the boundary link itself)
               ! Use link velocity directly as the representative velocity
               uc1D(n) = u1(LL)
            end if
         end do

      ! ======================================================================
      ! STAGE 2: Upwind velocity assignment (jaPure1D = 1 or 2)
      ! ======================================================================
         u1Du = 0.0_dp  ! initialize upwind velocities
         
         ! Assign upwind velocities on links based on flow direction
         do L = 1, lnx
            if (qa(L) > 0 .and. abs(uc1D(ln(1, L))) > 0) then 
               ! Positive discharge: use velocity from upstream node (node 1)
               u1Du(L) = uc1D(ln(1, L))
            else if (qa(L) < 0 .and. abs(uc1D(ln(2, L))) > 0) then
               ! Negative discharge: use velocity from upstream node (node 2)
               u1Du(L) = uc1D(ln(2, L))
            end if
         end do

      ! ======================================================================
      ! STAGE 3: Advanced 1D computation with storage effects (jaPure1D >= 3)
      ! ======================================================================
      elseif (jaPure1D >= 3) then

         ! Initialize arrays for advanced 1D computation
         q1D = 0.0_dp          ! storage-corrected discharges [m³/s]
         au1D = 0.0_dp         ! flow areas at link ends [m²]
         sar1D = 0.0_dp        ! surface areas at link ends [m²]
         volu1D = 0.0_dp       ! link volumes [m³]
         alpha_mom_1D = 0.0_dp ! momentum correction factors [-]
         alpha_ene_1D = 0.0_dp ! energy correction factors [-]
         
         ! Loop through 1D nodes for advanced computations
         do n = ndx2D + 1, ndxi
            nx = nd(n)%lnx

            ! Verify this is a valid 1D node (same check as Stage 1)
            ja1D = 1
            do LL = 1, nx
               L = nd(n)%ln(LL)
               La = abs(L)
               if (abs(kcu(La)) /= 1) then
                  ja1D = 0
               end if
            end do
            if (ja1D == 0) then
               cycle
            end if
            if (jaJunction1D == 0 .and. nx > 2) then
               cycle
            end if

            ! ----------------------------------------------------------------
            ! Sub-stage 3a: Compute geometric properties and net discharge
            ! ----------------------------------------------------------------
            q_net_in = 0.0_dp     ! net discharge into node [m³/s]
            surface_area = 0.0_dp ! total surface area around node [m²]
            
            do LL = 1, nx ! loop over all links connected to the node
               L = nd(n)%ln(LL)   ! signed link number
               La = abs(L)        ! absolute link number

               half_link_length = 0.5 * dx(La)  ! half the link length [m]
               
               ! Determine which end of the link we're considering
               if (L > 0) then ! link points TO node: consider end of link
                  k = 2
               else ! link points FROM node: consider start of link
                  k = 1
               end if

               ! Compute water depth and cross-sectional properties
               h = max(0.0_dp, s1(n) - bob(k, La)) ! water depth [m]
               
               ! Get total (flow + storage) cross-section
               call getprof_1D(La, h, total_cs_area, total_width, JACSTOT, CALCCONV, perim)
               
               ! Get flow-only cross-section
               call getprof_1D(La, h, flow_cs_area, flow_width, JACSFLW, CALCCONV, perim)
               
               ! Compute and store geometric properties
               link_surface_area = total_width * half_link_length  ! surface area of half-link [m²]
               wu1D(k, La) = total_width      ! surface width at link end [m]
               au1D(k, La) = flow_cs_area     ! flow area at link end [m²]
               sar1D(k, La) = link_surface_area ! surface area of half-link [m²]

               ! Accumulate total properties for the node
               surface_area = surface_area + link_surface_area
               volu1D(La) = volu1D(La) + flow_cs_area * half_link_length

               ! Net discharge: positive if INTO node, negative if OUT OF node
               q_net_in = q_net_in + real(sign(1, L), kind=dp) * qa(La)
            end do

            ! ----------------------------------------------------------------
            ! Sub-stage 3b: Apply storage corrections and compute correction factors
            ! ----------------------------------------------------------------
            qu_in = 0.0_dp    ! corrected momentum flux into node [m⁴/s²]
            qu_out = 0.0_dp   ! corrected momentum flux out of node [m⁴/s²]
            qu2_in = 0.0_dp   ! corrected kinetic energy flux into node [m⁵/s³]
            qu2_out = 0.0_dp  ! corrected kinetic energy flux out of node [m⁵/s³]
            
            ! Rate of water level change due to net inflow/outflow [m/s]
            dzw_dt = q_net_in / surface_area
            
            do LL = 1, nx ! loop over all links connected to the node
               L = nd(n)%ln(LL)  ! signed link number
               La = abs(L)       ! absolute link number

               ! Apply storage correction to discharge based on link orientation
               if (L > 0) then 
                  ! Link points TO node: reduce discharge by storage on downstream half-link
                  link_surface_area = sar1D(2, La)
                  flow_cs_area = au1D(2, La)
                  q = qa(La) - link_surface_area * dzw_dt  ! storage correction
                  q1D(2, La) = q
               else 
                  ! Link points FROM node: increase discharge by storage on upstream half-link
                  link_surface_area = sar1D(1, La)
                  flow_cs_area = au1D(1, La)
                  q = qa(La) + link_surface_area * dzw_dt  ! storage correction
                  q1D(1, La) = q
               end if

               ! Compute momentum and energy fluxes with corrected discharge
               if ((L * q) >= 0.0_dp) then 
                  ! INFLOW to node
                  u = u1(La)  ! use link velocity directly
                  if ((q * u) > 0) then 
                     ! Consistent flow direction: contribute to inflow terms
                     qu_in = qu_in + abs(q * u)      ! momentum flux
                     qu2_in = qu2_in + abs(q * u**2) ! kinetic energy flux
                  else 
                     ! Inconsistent flow direction: treat as stagnant inflow (no contribution)
                  end if
               elseif (flow_cs_area > 0.0_dp) then 
                  ! OUTFLOW from node
                  u = q / flow_cs_area  ! compute velocity from corrected discharge
                  qu_out = qu_out + abs(q * u)      ! momentum flux
                  qu2_out = qu2_out + abs(q * u**2) ! kinetic energy flux
               end if
            end do

            ! Compute correction factors for momentum and energy equations
            ! These factors account for non-uniform velocity distributions
            alpha_mom_1D(n) = qu_in / max(1e-20_dp, qu_out)   ! momentum correction
            alpha_ene_1D(n) = qu2_in / max(1e-20_dp, qu2_out) ! energy correction
         end do
      end if

   end subroutine setuc1d

end module m_setuc1d
