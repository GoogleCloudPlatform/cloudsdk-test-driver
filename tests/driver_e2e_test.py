# Copyright 2016 The Cloud SDK Test Driver Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for cloudsdk_test_driver."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import json
import os
import tempfile
import unittest

from cloudsdk_test_driver import constants
from cloudsdk_test_driver import driver


class GcloudTestDriverNoDestroy(unittest.TestCase):

  def cleanup(self):
    os.environ[constants.DRIVER_LOCATION_ENV] = self.location
    driver.Destroy()

  def testRunTwiceNoDestroy(self):
    # Forgetting to call Destroy mainly means that the installation location is
    # not cleaned up. By default this would leave files in the temp directory.
    # It's best not to leave such files around taking up disk space, but they
    # shouldn't hurt anything if the disk's not full.

    # After Init, imitate forgetting to call Destroy by removing the environment
    # variable tracking the installation location.
    driver.Init()
    self.location = os.environ[constants.DRIVER_LOCATION_ENV]
    del os.environ[constants.DRIVER_LOCATION_ENV]
    self.addCleanup(self.cleanup)

    # Verify that things still work.
    with driver.Manager():
      sdk = driver.DefaultSDK()
      _, _, ret = sdk.RunGcloud(['config', 'list'])
      self.assertEqual(0, ret)

  def testRunTwiceNoDestroyFixedPath(self):
    # If you're using a fixed root directory, not calling Destroy will behave a
    # little differently. Instead of leaking the previous installation, it will
    # just reuse it.
    root_directory = tempfile.mkdtemp()

    # After Init, imitate forgetting to call Destroy by removing the environment
    # variable tracking the installation location.
    driver.Init(root_directory=root_directory)
    self.location = os.environ[constants.DRIVER_LOCATION_ENV]
    del os.environ[constants.DRIVER_LOCATION_ENV]
    self.addCleanup(self.cleanup)

    # If the root directory was set, the driver should be using it
    self.assertEqual(root_directory, self.location)

    # Verify that things still work.
    with driver.Manager(root_directory=root_directory):
      sdk = driver.DefaultSDK()
      _, _, ret = sdk.RunGcloud(['config', 'list'])
      self.assertEqual(0, ret)

      self.assertEqual(
          root_directory, os.environ[constants.DRIVER_LOCATION_ENV])

  def testRunInitializeCommandsTwice(self):
    # The SDK.RunInitializationCommands function should be called automatically
    # by the factory functions, but running them again manually should be a
    # no-op.
    with driver.Manager():
      sdk = driver.DefaultSDK()
      sdk.RunInitializationCommands()
      _, _, ret = sdk.RunGcloud(['config', 'list'])
      self.assertEqual(0, ret)


class GcloudTestDriverHelp(unittest.TestCase):

  def testHelpCommand(self):
    # The help commands do not return JSON results unlike almost all normal
    # commands. Verify that they're still handled properly.
    with driver.Manager():
      sdk = driver.DefaultSDK()
      out, _, ret = sdk.RunGcloud(['config', '--help'])
      self.assertEqual(0, ret)
      # Just verify that whatever RunGcloud returns is valid as a JSON object.
      json.dumps(out)


class GcloudTestAlternateTar(unittest.TestCase):

  def testInstallPreviousVersion(self):
    # Make sure the driver can install from one of the archived versions.
    with driver.Manager(
        tar_location='https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-sdk-140.0.0-linux-x86_64.tar.gz'):
      sdk = driver.DefaultSDK()
      sdk.RunInitializationCommands()
      _, _, ret = sdk.RunGcloud(['config', 'list'])
      self.assertEqual(0, ret)


if __name__ == '__main__':
  unittest.main()
