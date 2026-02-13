# Managing test case data with `dvc`

## Table of contents
- [Introduction](#introduction)
- [Versioning the test case data](#versioning-the-test-case-data)
- [HOWTO: Download test case data](#howto-download-test-case-data)

## Introduction
We have a large collection of test cases that we can run with `TestBench.py`. Each
test case has input files, reference files and documentation. Furthermore, 
`TestBench.py` requires a config file which contains information on how to run
the test cases, and where to find the test case data (You can find plenty
of examples of these in the [configs](./configs/) directory).

This document describes how to perform some common tasks with test case data,
such as:
- Downloading the input files of one or several test cases.
- Updating the input files or reference files of a test case.
- Uploading input data for an entirely new test case.

This document does not contain any information about config files for 
`TestBench.py`. If you need help writing or updating a config file, you can take
a look at the [`TestBench.py documentation`](./doc/readme-testbench.pdf)

## Versioning the test case data
Running a test case with `TestBench.py` performs the following steps:
1. Download the test case input files.
2. Download the test case reference (output) files.
3. Run a program (or several programs) using the input files. This produces output 
files.
4. Compare the output files produced in the previous step with the reference
files.
5. The test fails if programs fail to generate the expected output files, or if the
differences between the output and the reference files are not within tolerance.

`TestBench.py` allows the developers to remain confident that the software still 
produces correct output as changes to the software are introduced. We don't allow 
changes to the software that produce differences above tolerances in any test case.
The trouble is that we need to store the test case input and reference files somewhere.

Just like our code, our test case data changes over time.
New functionality requires new test cases. So it should be possible to create new
test cases as new features are introduced. Sometimes either the input files or 
reference files for an existing test case need to be updated. For instance, the input
files may be using deprecated or obsolete functionality. 
A change in the software may produce differences above tolerances. Sometimes the 
differences are actually regarded as an improvement. In that case the reference files 
need to be updated. Over time, a history of test case data emerges. We want to be able to
roll back to a specific version of the software and run the test cases with the test
case data as it was at the time that version of the software was made. Furthermore,
we want developers to be able to make changes to test case data simultaneously without 
unnecessary conflicts.

We already version our software with `git`. Ideally, we
could track all of our test case data with `git` as well. This way, our test
case data would be versioned automatically and it would always be up-to-date 
with the software in the repository. Unfortunately, this is infeasible for a 
couple of reasons:
1. Some test cases contain input files larger than the file size limit for the git
remote (GitHub).
2. Our GitHub repository is publicly accessible. But some of the test cases that
we run should not be publically accessible.
3. The number of files and total size of the test case data are both quite large. This
makes it somewhat impracticle to clone the repository, unless you explicitly exclude
the test case data. Our build agents clone the repository all the time, and most of the
time they need only a tiny percentage of the test case data.

We need to store the test case data somewhere where it is not
publicly accessible, and in a place that can handle many (large) files. 
The test case data should be versioned, in such a way that we can easily link a commit to 
the correct test case data. It should be possible to download test case data only when it
is needed. Furthermore, it should not be difficult to create new test case data and
update existing test case data. Updates to the test case data can be done in a branch, and 
multiple developers should be able to make changes to the test case data simultaneously in 
different branches, without unnecessary conflicts. `dvc` fits these requirements quite 
closely.

## HOWTO: Download test case data
