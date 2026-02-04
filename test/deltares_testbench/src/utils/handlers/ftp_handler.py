"""FTP handler.

Copyright (C)  Stichting Deltares, 2026
"""

import os
import urllib.parse as parse
from ftplib import FTP, error_perm
from pathlib import Path
from typing import Optional

from src.config.credentials import Credentials
from src.utils.handlers.i_handler import IHandler
from src.utils.logging.i_logger import ILogger


class FTPHandler(IHandler):
    """Upload and download for ftp paths."""

    # Download data from location
    # input: from, to and credentials
    def download(
        self,
        from_path: Path | str,
        to_path: Path,
        credentials: Credentials,
        version: Optional[str],
        logger: ILogger,
    ) -> None:
        if isinstance(from_path, Path):
            raise TypeError("from_path must be of type str for FTPHandler")
        logger.debug(f"setting up connection to FTP: {from_path}")
        url = parse.urlparse(from_path)
        ftp = FTP(url.netloc)
        if credentials:
            ftp.login(credentials.username, credentials.password)
            logger.debug(f"connecting as: {credentials.username}")
        else:
            ftp.login()
        ftp.cwd(url.path)
        logger.debug(f"going to root: {url.path}")
        # create root on filesystem
        if not to_path.exists():
            to_path.mkdir(parents=True)
        logger.debug("analysing directory structure on ftp")
        self.__traverse_directory_download__(ftp, "/", to_path, logger)
        ftp.close()

    # recursive traverse, fills ftpdirs array
    # cwd is the local working directory
    # frompath is relative dir of local system
    # destination is abs dir of ftp
    # topath is relative dir of ftp
    def __traverse_directory_upload__(self, ftp, cwd, frompath, destination, topath, logger: ILogger):
        try:
            ftp.cwd(destination)
            if topath:
                ftp.cwd(topath)
            ndir = os.path.basename(os.path.normpath(frompath))
            ftp.mkd(ndir)
            logger.debug(f"built ftp frompath : {frompath.replace(os.sep, '/')}")
        except error_perm:
            # invalid entry (ensure input form: "/dir/folder/something/")
            logger.debug(f"frompath {frompath.replace(os.sep, '/')} already exists")
        # list children:
        filelist = os.listdir(os.path.join(cwd, frompath))
        for locfile in filelist:
            if os.path.isdir(os.path.join(cwd, frompath, locfile)):
                topath = "/"
                if frompath:
                    parts = os.path.split(frompath)
                    if parts:
                        for part in parts:
                            topath = topath + part + "/"
                self.__traverse_directory_upload__(
                    ftp,
                    cwd,
                    os.path.join(frompath, locfile),
                    destination,
                    topath,
                    logger,
                )
            else:
                ftp.cwd("/" + destination + frompath.replace(os.sep, "/"))
                with open(os.path.join(cwd, frompath, locfile)) as lf:
                    ftp.storbinary("STOR " + locfile, lf)

                logger.debug(f"uploaded {locfile}")
        return

    # recursive traverse download files
    # frompath is str of the form "/dir/folder/something/"
    # frompath should be the abs frompath to the root FOLDER of the file tree to download
    def __traverse_directory_download__(self, ftp: FTP, path: str, destination: Path, logger: ILogger) -> None:
        """Recursively traverse an FTP directory tree and download all files into the destination folder."""
        topath = destination / Path(path.lstrip("/"))
        try:
            ftp.cwd(path)
            # clone path to destination
            topath.mkdir(parents=True, exist_ok=True)
            logger.debug(f"built path : {topath}")
        except OSError:
            # folder already exists at destination
            pass
        except error_perm as exc:
            # invalid entry (ensure input form: "/dir/folder/something/")
            raise OSError(f"error: could not change to {path}") from exc
        # list children:
        filelist = ftp.nlst()
        for ftpfile in filelist:
            try:
                # this will check if ftpfile is folder:
                ftp.cwd(path + ftpfile + "/")
                # if so, explore it:
                self.__traverse_directory_download__(ftp, path + ftpfile + "/", destination, logger)
            except error_perm:
                # possibly need a permission exception catch:
                with open(topath / ftpfile, "wb") as ff:
                    ftp.retrbinary("RETR " + ftpfile, ff.write)

                logger.debug(f"downloaded {ftpfile}")
        return
