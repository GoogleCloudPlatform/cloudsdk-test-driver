# Copyright 2016 Google Inc. All Rights Reserved.
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
"""An example of the basic use case for cloudsdk_test_driver."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import unittest

from cloudsdk_test_driver import driver


class GcloudTestDriverExampleTest(unittest.TestCase):

  def testConfigList(self):
    sdk = driver.DefaultSDK()
    _, _, ret = sdk.RunGcloud(['config', 'list'])
    self.assertEqual(0, ret)


if __name__ == '__main__':
  with driver.Manager():
    unittest.main()
