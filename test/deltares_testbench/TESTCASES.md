# Managing test case data with `dvc`
We have a large collection of test cases that we can run with `TestBench.py`. Each
test case has input files, reference files and documentation. Furthermore, 
`TestBench.py` requires a config file which contains information on how to run
the test cases, and where to find the test case data (You can find plenty
of examples of these in the [configs](./configs/) directory).

This document describes how to perform some common tasks with the test case data,
like for instance:
- Downloading the input files of one or several test cases.
- Updating the input files or reference files of a case.
- Uploading input data for an entirely new test case.

This document does not contain any information about config files for 
`TestBench.py`. If you need help writing or updating a config file, you can take
a look at the [`TestBench.py documentation`](./doc/readme-testbench.pdf)

## Versioning the test case data
Test cases run with `TestBench.py` usually adhere to the following template:
1. Download the test case input files.
2. Download the test case reference (output) files.
3. Run a program (or several) using the input files. This produces output files.
4. Compare the output files produced in the previous step with the reference
files.
5. The test fails if program fails to generate output files, or if the differences
between the output and the references is not within tolerance.

The input and reference files need to be stored somewhere. `TestBench.py` allows
the developers to remain confident that the software still produces correct output
as changes to the software are introduced. We don't allow changes to the software
that produce differences above tolerances in any test case.

New functionality requires new test cases. So it should be possible to create new
test cases as new features are introduced. Sometimes either the input files or reference
files for an existing test case need to be updated. For instance, the input files may be
using deprecated or obsolete functionality. It may also happen that a change in the 
software produces differences above tolerances, but the differences are actually deemed
an improvement. In the latter case the reference files need to be updated.

We already version our software with `git`. We could track all of our test case data
in this repository as well. This way, our test case data would be versioned
automatically and it would always be up-to-date with the software in our repository. 
Unfortunately, this is infeasible for a couple of reasons:
1. 
The trouble begins when the test
case data also changes over time. Not only do we want to be able to checkout an
old version of the software and build it. We also want to be able to test older
versions with the test case data as it was at the time the older versions were
released.



