"""Test helper utilities for XML configuration generation."""

import io
import os
import textwrap
from datetime import datetime, timezone
from pathlib import Path

from pyfakefs.fake_filesystem import FakeFilesystem

from src.config.dependency import Dependency
from src.config.test_case_path import TestCasePath


class XMLConfigHelper:
    """Helper class for generating XML configuration files for testing."""

    @staticmethod
    def make_test_case_config_xml(
        filesystem: FakeFilesystem,
        test_case_path: TestCasePath | None = None,
        dependency: Dependency | None = None,
        reference_value: str | None = "0.0",
        include: str | None = "",
        case_root: str | None = "{server_base_url}/cases",
        reference_root: str | None = "{server_base_url}/references",
        config_path: Path | None = None,
    ) -> Path:
        """Make config xml with some default values."""
        # Build `path` element.
        test_case_path = test_case_path or TestCasePath("test/case")
        path_elem = "<path"
        if test_case_path.version is not None:
            path_elem += f' version="{test_case_path.version}"'
        path_elem += f">{test_case_path.prefix}</path>"

        # Build `dependency` element.
        if dependency:
            dependency_elem = f'<dependency local_dir="{dependency.local_dir}"'
            if dependency.version is not None:
                dependency_elem += f' version="{dependency.version}"'
            dependency_elem += f">{dependency.cases_path}</dependency>"
        else:
            dependency_elem = ""

        text = textwrap.dedent(
            rf"""
            <?xml version="1.0" encoding="iso-8859-1"?>
            <deltaresTestbench_v3 xmlns="http://schemas.deltares.nl/deltaresTestbench_v3"
                xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                xmlns:xi="http://www.w3.org/2001/XInclude"
                xsi:schemaLocation="http://schemas.deltares.nl/deltaresTestbench_v3 http://content.oss.deltares.nl/schemas/deltaresTestbench_v3-2.00.xsd">
                <config>
                    <credentials>
                        <credential name="deltares">
                            <username></username>
                            <password></password>
                        </credential>
                    </credentials>
                    <localPaths>
                        <testCasesDir>.\data\cases</testCasesDir>
                        <enginesDir>.\data\engines</enginesDir>
                        <referenceDir>.\data\references_results</referenceDir>
                    </localPaths>
                    <locations>
                        <location name="dsctestbench-cases">
                            <credential ref="deltares" />
                            <root>{case_root}</root>
                        </location>
                        <location name="dsctestbench-references">
                            <credential ref="deltares" />
                            <root>{reference_root}</root>
                        </location>
                    {additional_locations}
                    </locations>
                </config>
                <programs>
                    <program name="foo">
                        <path>foo.exe</path>
                    </program>
                </programs>

                <defaultTestCases>
                    <testCase name="default_test_case">
                        <location ref="dsctestbench-cases" type="input">
                            <from>.</from>
                        </location>
                        <location ref="dsctestbench-references" type="reference">
                            <from>win64</from>
                        </location>
                        <maxRunTime>60.0</maxRunTime>
                    </testCase>
                </defaultTestCases>
                <testCases>
                    <testCase name="run_foo" ref="default_test_case">
                        {path_elem}
                        {dependency_elem}
                        <programs>
                            <program ref="foo"></program>
                        </programs>
                        <maxRunTime>60.0</maxRunTime>
                        <checks>
                            <file name="foo.out" type=".out">
                                <parameters>
                                    <parameter name="foo" toleranceRelative="{reference_value}" />
                                </parameters>
                            </file>
                        </checks>
                    </testCase>
                </testCases>
                {include}
            </deltaresTestbench_v3>
            """
        )

        target_path = config_path or Path("config.xml")
        return XMLConfigHelper.write_config_file(filesystem, target_path, io.BytesIO(text.strip().encode("utf-8")))

    def setup_include_element_xml(
        self, filesystem: FakeFilesystem, tmp_dir: Path, version_attr: str | None = "version="
    ) -> Path:
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        version = now.isoformat().split("+", 1)[0]
        include_xml = f"""
        <testCases xmlns="http://schemas.deltares.nl/deltaresTestbench_v3">
            <testCase name="run_foo" ref="default_test_case">
                <path {version_attr}"{version}">local/dir</path>
                <programs>
                    <program ref="foo"></program>
                </programs>
                <maxRunTime>60.0</maxRunTime>
                <checks>
                    <file name="foo.out" type=".out">
                        <parameters>
                            <parameter name="foo" toleranceRelative="0.0" />
                        </parameters>
                    </file>
                </checks>
            </testCase>
        </testCases>
        """
        xml_include_path = tmp_dir / "include.xml"
        filesystem.create_file(os.fspath(xml_include_path), contents=include_xml)
        include = f'<xi:include href="{os.fspath(xml_include_path)}"/>'

        return XMLConfigHelper.make_test_case_config_xml(
            filesystem=filesystem,
            include=include,
            config_path=tmp_dir / "config.xml",
        )

    @staticmethod
    def write_config_file(filesystem: FakeFilesystem, config_path: Path, content: io.BytesIO) -> Path:
        """Persist in-memory XML content to fake fs."""
        data = content.getvalue() if hasattr(content, "getvalue") else content
        if not isinstance(data, (str, bytes, bytearray)):
            raise TypeError(f"Unsupported config content type: {type(content)!r}")

        parent = config_path.parent
        if parent not in (Path("."), Path("")):
            parent_path = os.fspath(parent)
            if not filesystem.exists(parent_path):
                filesystem.create_dir(parent_path)
        filesystem.create_file(
            os.fspath(config_path),
            contents=(data if isinstance(data, (str, bytes)) else bytes(data)),
        )
        return config_path
