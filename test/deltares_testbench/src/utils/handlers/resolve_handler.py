"""Resolve Handler helper.

Copyright (C)  Stichting Deltares, 2026
"""

import re
import ssl
import urllib.parse as parse
import urllib.request as url_lib
from abc import ABC
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError

from src.config.credentials import Credentials
from src.config.types.handler_type import HandlerType
from src.utils.logging.i_logger import ILogger


class ResolveHandler(ABC):
    """Detect type of handler behind a path."""

    @classmethod
    def detect(cls, path: Path | str, logger: ILogger, credentials: Optional[Credentials] = None) -> HandlerType:
        """Detect which protocol handler is needed for the path.

        Parameters
        ----------
        path : Path
            URL.
        credentials : Optional[Credentials]
            Credentials to use.

        Returns
        -------
        HandlerType
            Detected handler type.
        """
        path_str = str(path)
        logger.debug(f"detecting handler for {path_str}")

        if path_str.endswith(".dvc"):
            return HandlerType.DVC
        elif re.search(
            r"^\\(\\)?[A-Za-z0-9]+|^\/\/[A-Za-z0-9]+", path_str
        ):  # assume network path starts with either [//] or [\\]
            return HandlerType.NET
        elif re.search(r"[A-Za-z]{1}\:\\|^\/{1}[A-Za-z0-9]|\.\.", path_str):  # assume local path handler [X:\] or [/]
            return HandlerType.PATH
        elif re.search(r"^ftp(s)?://", path_str):
            return HandlerType.FTP
        elif re.match(r"^https://minio", path_str) or re.match(r"^https://s3.deltares.nl", path_str):
            return HandlerType.MINIO
        else:
            return cls.__detect_by_opening_url(path_str, logger, credentials)

    @classmethod
    def __detect_by_opening_url(cls, path: str, logger: ILogger, credentials: Optional[Credentials]) -> HandlerType:
        """Try to open http connections to detect protocol header (recursive analysis to root of path).

        Parameters
        ----------
        path : str
            URL.
        credentials : Optional[Credentials]
            Credentials to use.

        Returns
        -------
        HandlerType
            Detected handler type.
        """
        if credentials:
            password_mgr = url_lib.HTTPPasswordMgrWithDefaultRealm()
            scheme, netloc, _, _, _, _ = parse.urlparse(path)
            password_mgr.add_password(
                None,
                f"{scheme}://{netloc}/",
                credentials.username,
                credentials.password,
            )
            handler = url_lib.HTTPBasicAuthHandler(password_mgr)
            # due to failing SSL certificate (some ICT updates) we disable certificate validation
            if hasattr(ssl, "create_default_context"):
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                ssl_handler = url_lib.HTTPSHandler(context=ctx)
                opener = url_lib.build_opener(handler, ssl_handler)
            else:
                opener = url_lib.build_opener(handler)

            url_lib.install_opener(opener)
        try:
            logger.debug(f"Trying to urlopen {path}")
            response = url_lib.urlopen(path)
            data = response.read().decode("utf-8")
            if "<!doctype html" in data.lower():
                return HandlerType.WEB
            else:
                return HandlerType.NONE
        except HTTPError as exception:
            if exception.code == 401:
                logger.error("Authentication error")
                if credentials:
                    logger.error("Credentials missing!")
            else:
                logger.warning(f"The server could not fulfill the request ({path}). Error code: {exception.code}")
                if path.count("/") > 2:
                    newpath = path[: path.rfind("/")]
                    return cls.__detect_by_opening_url(newpath, logger, credentials)
        except URLError as exception:
            logger.error(f"Failed to reach server ({path}). Reason: {exception.reason}")
        except Exception as exception:
            logger.debug(str(exception))

        return HandlerType.NONE
