"""Handler Factory.

Copyright (C)  Stichting Deltares, 2026
"""

import os
from abc import ABC
from pathlib import Path
from typing import List, Optional

from src.config.credentials import Credentials
from src.config.types.handler_type import HandlerType
from src.suite.program import Program
from src.utils.handlers.dvc_handler import DvcHandler
from src.utils.handlers.ftp_handler import FTPHandler
from src.utils.handlers.http_handler import HTTPHandler
from src.utils.handlers.i_handler import IHandler
from src.utils.handlers.local_net_handler import LocalNetHandler
from src.utils.handlers.minio_handler import MinIOHandler
from src.utils.handlers.resolve_handler import ResolveHandler
from src.utils.logging.i_logger import ILogger
from src.utils.paths import Paths
from src.utils.unzipper import Unzipper


class HandlerFactory(ABC):
    """Chooses which type of handler is used for upload and download actions."""

    @classmethod
    def __get_handler(
        cls,
        destination_path: Path | str,
        programs: List[Program],
        logger: ILogger,
        credentials: Optional[Credentials] = None,
    ) -> IHandler:
        """Create handler based on destination path.

        Parameters
        ----------
        to_path : Path | str
            Destination path.
        credentials : Credentials, optional
            Credentials needed for connection. Defaults to None.

        Raises
        ------
        AttributeError
            Of handler could not be detected.

        Returns
        -------
        IHandler
            Specific handler.
        """
        handler_type = ResolveHandler.detect(destination_path, logger, credentials)
        handler: IHandler

        if handler_type == HandlerType.WEB:
            logger.debug(f"using HTTP handler for {destination_path}")
            handler = HTTPHandler()
        if handler_type == HandlerType.FTP:
            logger.debug(f"using FTP handler for {destination_path}")
            handler = FTPHandler()
        if handler_type == HandlerType.NET or handler_type == HandlerType.PATH:
            logger.debug(f"using LocalNet handler for {destination_path}")
            handler = LocalNetHandler()
        if handler_type == HandlerType.MINIO:
            logger.debug(f"using MinIO handler for {destination_path}")
            handler = MinIOHandler()
        if handler_type == HandlerType.DVC:
            logger.debug(f"using DVC handler for {destination_path}")
            handler = DvcHandler()
        if handler_type == HandlerType.NONE:
            raise AttributeError("upload :: no type specified")

        return handler

    @classmethod
    def download(
        cls,
        from_path: Path | str,
        to_path: Path,
        programs: List[Program],
        logger: ILogger,
        credentials: Optional[Credentials] = None,
        version: Optional[str] = None,
        unzip: bool = False,
    ) -> None:
        """Download data from location.

        Parameters
        ----------
        from_path : Path | str
            Source path.
        to_path : Path
            Target path.
        credentials : Optional[Credentials], optional
            Credentials to use. Defaults to None.
        version : Optional[str], optional
            Version. Defaults to None.
        unzip : bool, optional
            Try to unzip file. Defaults to False.
        """
        rtp = Paths().rebuild_to_local_path(to_path)
        os.makedirs(rtp, exist_ok=True)

        handler = cls.__get_handler(from_path, programs, logger, credentials)
        handler.download(from_path, rtp, credentials, version, logger)
        if unzip:
            Unzipper().recursive(rtp, logger)
