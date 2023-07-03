#!/usr/bin/env python3

import aws_cdk as cdk

from cdk_workshop.cdk_workshop_stack import TestStack2

app = cdk.App()
TestStack2(app, "TestStack2")

app.synth()
