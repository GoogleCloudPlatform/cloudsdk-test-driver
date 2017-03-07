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

import copy
import json
import os
import random
import re
import shutil
import StringIO
import subprocess
import sys
import tarfile
import tempfile
import unittest
import urllib2

from cloudsdk_test_driver import _config
from cloudsdk_test_driver import _sdk_tar
from cloudsdk_test_driver import constants
from cloudsdk_test_driver import driver
from cloudsdk_test_driver import error

import mock


def setUpModule():
  os.chdir(os.path.dirname(__file__))


class Base(unittest.TestCase):

  def StartPatch(self, *args, **kwargs):
    patch = mock.patch(*args, **kwargs)
    self.addCleanup(patch.stop)
    return patch.start()

  def StartObjectPatch(self, *args, **kwargs):
    if 'autospec' not in kwargs and 'new' not in kwargs:
      kwargs['autospec'] = True
    patch = mock.patch.object(*args, **kwargs)
    self.addCleanup(patch.stop)
    return patch.start()

  def StartDictPatch(self, *args, **kwargs):
    patch = mock.patch.dict(*args, **kwargs)
    self.addCleanup(patch.stop)
    return patch.start()

  def MockPopen(self):
    self.mock_popen = mock.Mock(
        returncode=0, communicate=mock.Mock(return_value=('foo', 'bar')))
    self.popen_patch = self.StartObjectPatch(
        subprocess, 'Popen', new=mock.Mock(return_value=self.mock_popen))

  def MockSDKFactoryDependencies(self):
    self.StartObjectPatch(random.SystemRandom, 'choice', return_value='x')

    self.environ = {
        'PATH': 'env_path',
        constants.PYTHON_ENV: 'env_python',
        constants.DRIVER_LOCATION_ENV: 'driver_location'
    }
    self.StartDictPatch(os.environ, self.environ, clear=True)

    self.path = ['sys_path']
    self.StartObjectPatch(sys, 'path', new=self.path)

    self.StartObjectPatch(sys, 'executable', new='sys_python')

    self.expected_sdk_dir = os.path.join(
        'driver_location', constants.SDK_FOLDER)
    self.expected_cwd = os.path.dirname(self.expected_sdk_dir)

    self.expected_config_name = 'configxxxxxxxx'

    self.expected_environ = copy.deepcopy(
        constants.DEFAULT_CONFIG['environment_variables'])
    self.expected_environ.update({
        'PATH': os.pathsep.join(
            [os.path.join(self.expected_sdk_dir, 'bin'), self.environ['PATH']]),
        # os.environ[PYTHON_ENV] will be picked up by Init, but not by SDK. For
        # the SDK, you have to pass such environment variables into the
        # constructor.
        constants.PYTHON_ENV: 'sys_python',
        constants.PYTHON_PATH: 'sys_path',
        constants.CONFIG_ENV: os.path.join(
            self.expected_sdk_dir, self.expected_config_name),
    })

    # If calling this, the errors are likely to be long
    self.maxDiff = None

  def assertCalledOnceWithSomeArgs(self, mock_object, *args, **kwargs):
    calls = mock_object.call_args_list

    # Assert called once
    self.assertEqual(1, len(calls))

    call_args, call_kwargs = calls[0]

    # Assert args is a subset of call args (can't actually use sets since these
    # might contain unhashable types)
    for arg in args:
      self.assertIn(arg, call_args)

    # Assert kwargs is a subset of call kwargs and match for matching keys
    for key, value in kwargs.items():
      self.assertIn(key, call_kwargs)
      self.assertEqual(
          value, call_kwargs[key],
          'Values do not match for key [{key}]'.format(key=key))

  def RaiseCommandNotCalled(self, command, calls):
    raise AssertionError(
        '[{command}] not called:\n{calls}'.format(
            command=command, calls='\n'.join([str(c) for c in calls])))

  def GetSDK(self):
    """Create an SDK with some default values."""
    self.config = driver.Config()
    self.driver_location = 'driver_location'
    self.config_name = 'configxxxxxxxx'
    self.sdk_dir = os.path.join(self.driver_location, constants.SDK_FOLDER)
    self.environ = _config.PrepareEnviron({}, self.config_name, self.sdk_dir)
    return driver.SDK(
        self.config, self.sdk_dir, self.config_name, self.environ)


class CloudSDKTestDriverConfigTest(unittest.TestCase):

  @classmethod
  def setUpClass(cls):
    # If there's an infinite recursion in the dictionary code, this will help
    # make the error messages more readable.
    cls._old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(100)

  @classmethod
  def tearDownClass(cls):
    # Put the recursion limit back where it was.
    sys.setrecursionlimit(cls._old_limit)

  def testConfigDefault(self):
    config = driver.Config()
    expected = copy.deepcopy(constants.DEFAULT_CONFIG)
    self.assertEqual(expected, dict(config))

  def testConfigLen(self):
    config = driver.Config()
    expected = copy.deepcopy(constants.DEFAULT_CONFIG)
    self.assertEqual(len(expected), len(config))

  def testConfigKeys(self):
    config = driver.Config()
    expected = copy.deepcopy(constants.DEFAULT_CONFIG)
    self.assertEqual(sorted(expected.keys()), sorted(config.keys()))
    for key in config:
      self.assertEqual(expected[key], config[key])

  def testConfigGetValue(self):
    config = driver.Config()
    self.assertEqual(constants.DEFAULT_CONFIG['properties'],
                     config['properties'])
    self.assertEqual(constants.DEFAULT_CONFIG['properties'],
                     config.properties)

  def testConfigChangeValue(self):
    config = driver.Config()
    config.project = 'foo'
    self.assertEqual('foo', config['project'])
    self.assertEqual('foo', config.project)
    config['project'] = 'bar'
    self.assertEqual('bar', config['project'])
    self.assertEqual('bar', config.project)

  def testConfigAddNewValue(self):
    config = driver.Config()
    with self.assertRaises(error.ConfigError):
      config['foo'] = 'bar'
    with self.assertRaises(error.ConfigError):
      config.foo = 'bar'

  def testConfigInitChangeValue(self):
    config = driver.Config(project='foo')
    self.assertEqual('foo', config['project'])
    self.assertEqual('foo', config.project)

  def testConfigInitInvalidProperty(self):
    with self.assertRaises(error.ConfigError):
      driver.Config(foo='bar')

  def testImmutableConfigImmutable(self):
    config = driver.Config()
    immutable = _config.ImmutableConfig(config)
    with self.assertRaises(error.ConfigError):
      immutable.project = 'foo'
    with self.assertRaises(error.ConfigError):
      immutable['project'] = 'foo'
    self.assertEqual(
        constants.DEFAULT_CONFIG['project'], immutable.project)

  def testImmutableConfigSeparation(self):
    config = driver.Config()
    immutable = _config.ImmutableConfig(config)
    config.project = 'foo'
    self.assertEqual(
        constants.DEFAULT_CONFIG['project'], immutable.project)

  def testImmutableConfigEquals(self):
    cfg1 = _config.ImmutableConfig(driver.Config())
    cfg2 = _config.ImmutableConfig(driver.Config())
    cfg3 = _config.ImmutableConfig(driver.Config(project='foo'))
    self.assertEqual(cfg1, cfg2)
    self.assertNotEqual(cfg1, cfg3)

  def testConfigPartialYAML(self):
    config = driver.Config(filename='testdata/test_partial.yaml')
    expected = copy.deepcopy(constants.DEFAULT_CONFIG)
    expected['project'] = 'foo'
    self.assertEqual(expected, dict(config))

  def testConfigBadKeyYAML(self):
    with self.assertRaises(error.ConfigError):
      driver.Config(filename='testdata/test_bad_key.yaml')

  def testConfigInvalidYAML(self):
    with self.assertRaisesRegexp(error.ConfigError, 'dictionary'):
      driver.Config(filename='testdata/test_not_dict.yaml')

  def testConfigLockedEnvironmentVariable(self):
    with self.assertRaisesRegexp(error.ConfigError, 'CLOUDSDK_CONFIG'):
      driver.Config(filename='testdata/test_bad_env.yaml')
    with self.assertRaisesRegexp(error.ConfigError, 'CLOUDSDK_CONFIG'):
      driver.Config(**{'environment_variables': {'CLOUDSDK_CONFIG': 'foo'}})

  def testConfigLockedEnvironmentVariableOnLoad(self):
    config = driver.Config()
    with self.assertRaisesRegexp(error.ConfigError, 'CLOUDSDK_CONFIG'):
      config.LoadFile('testdata/test_bad_env.yaml')

  def testImmutableHash(self):
    config = driver.Config()
    immutable1 = _config.ImmutableConfig(config)
    config.project = 'foo'
    immutable2 = _config.ImmutableConfig(config)
    config = driver.Config()
    immutable3 = _config.ImmutableConfig(config)
    self.assertNotEqual(hash(immutable1), hash(immutable2))
    self.assertEqual(hash(immutable1), hash(immutable3))


class GcloudTestDriverSDKConfigTest(Base):

  def setUp(self):
    self.MockSDKFactoryDependencies()
    self.MockPopen()

  def testSDKDefaultConfig(self):
    sdk = driver.DefaultSDK()
    calls = self.popen_patch.mock_calls
    # This should generate no shell calls as none of the config values that
    # would cause commands to be run during creation are set.
    self.assertEqual(0, len(calls))

    sdk.Run(['config', 'list'])
    _, kwargs = self.popen_patch.call_args
    self.assertIn(
        os.path.join(self.expected_sdk_dir, 'bin'), kwargs['env']['PATH'])
    self.assertEqual(
        os.path.join(self.expected_sdk_dir, self.expected_config_name),
        kwargs['env']['CLOUDSDK_CONFIG'])

  def testSDKServiceAccount(self):
    sdk = driver.SDKFromDict(
        {'service_account_email': 'foo', 'service_account_keyfile': 'bar'})
    self.assertEqual('foo', sdk.config.service_account_email)
    self.assertEqual('bar', sdk.config.service_account_keyfile)
    calls = self.popen_patch.mock_calls
    for _, args, _ in calls:
      if args[0] == [
          'gcloud', 'auth', 'activate-service-account', 'foo',
          '--key-file', 'bar']:
        return
    self.RaiseCommandNotCalled('gcloud auth activate-service-account', calls)

  def testSetProject(self):
    sdk = driver.SDKFromArgs(project='foo')
    self.assertEqual('foo', sdk.config.project)
    calls = self.popen_patch.mock_calls
    for _, args, _ in calls:
      if args[0] == ['gcloud', 'config', 'set', 'project', 'foo']:
        return
    self.RaiseCommandNotCalled('gcloud config set project', calls)

  def testSetProperties(self):
    sdk = driver.SDKFromArgs(properties={'foo': 'bar'})
    self.assertEqual({'foo': 'bar'}, sdk.config.properties)
    calls = self.popen_patch.mock_calls
    for _, args, _ in calls:
      if args[0] == ['gcloud', 'config', 'set', 'foo', 'bar']:
        return
    self.RaiseCommandNotCalled('gcloud config set', calls)


class GcloudTestDriverSDKErrorTest(unittest.TestCase):

  def testNoInit(self):
    with self.assertRaises(error.SDKError):
      driver.DefaultSDK()


class GcloudTestDriverSDKConstructionTest(Base):

  def setUp(self):
    self.MockSDKFactoryDependencies()
    self.MockPopen()

    self.run_patch = self.StartObjectPatch(
        driver.SDK, 'RunGcloudRawOutput', return_value=('out', 'err', 0))

  def testInitialized(self):
    sdk = driver.DefaultSDK()
    sdk.Run(['config', 'list'])
    _, kwargs = self.popen_patch.call_args
    self.assertEqual(self.expected_cwd, kwargs['cwd'])

  def testNotInitialized(self):
    del os.environ[constants.DRIVER_LOCATION_ENV]
    with self.assertRaises(error.SDKError):
      driver.DefaultSDK()

  def testNoPythonExecutable(self):
    self.StartObjectPatch(sys, 'executable', new=None)
    with self.assertRaises(error.SDKError):
      driver.DefaultSDK()

  def testSpecifiedPythonPath(self):
    paths = ['path4', 'path5', 'path6']
    self.StartObjectPatch(sys, 'path', new=paths)
    sdk = driver.SDKFromArgs(environment_variables={'PYTHONPATH': 'path7'})

    sdk.Run(['config', 'list'])
    _, kwargs = self.popen_patch.call_args
    self.assertEqual(
        os.pathsep.join(['path7'] + paths),
        kwargs['env'][constants.PYTHON_PATH])

  def testDidntSpecifyPythonPath(self):
    paths = ['path4', 'path5', 'path6']
    self.StartObjectPatch(sys, 'path', new=paths)
    sdk = driver.DefaultSDK()

    sdk.Run(['config', 'list'])
    _, kwargs = self.popen_patch.call_args
    self.assertEqual(
        os.pathsep.join(paths),
        kwargs['env'][constants.PYTHON_PATH])

  def testNoPath(self):
    sdk = driver.DefaultSDK()

    sdk.Run(['config', 'list'])
    _, kwargs = self.popen_patch.call_args
    self.assertEqual(
        os.pathsep.join([
            os.path.join(self.expected_sdk_dir, constants.BIN_FOLDER),
            'env_path']),
        kwargs['env']['PATH'])

  def testPath(self):
    sdk = driver.SDKFromArgs(environment_variables={'PATH': 'path3'})

    sdk.Run(['config', 'list'])
    _, kwargs = self.popen_patch.call_args
    self.assertEqual(
        os.pathsep.join([
            os.path.join(self.expected_sdk_dir, constants.BIN_FOLDER),
            'path3', 'env_path']),
        kwargs['env']['PATH'])

  def testPathDuplicatesOsPath(self):
    sdk = driver.SDKFromArgs(
        environment_variables={
            'PATH': os.pathsep.join([self.environ['PATH'], 'path3'])})

    sdk.Run(['config', 'list'])
    _, kwargs = self.popen_patch.call_args
    self.assertEqual(
        os.pathsep.join([
            os.path.join(self.expected_sdk_dir, constants.BIN_FOLDER),
            'env_path', 'path3']),  # env_path should only show up once
        kwargs['env']['PATH'])


class GcloudTestDriverTestPrepareCommand(unittest.TestCase):

  def testPrepareCommandList(self):
    cmd = ['a', 'b', 'c,']
    self.assertEqual(cmd, driver._PrepareCommand(cmd))

  def testPrepareCommandTuple(self):
    cmd = ('a', 'b', 'c')
    self.assertEqual(list(cmd), driver._PrepareCommand(cmd))

  def testPrepareCommandString(self):
    cmds = [
        ('a b c', ['a', 'b', 'c']),
        (r'a\ b\ c', ['a b c']),
        ('a "b c"', ['a', 'b c']),
    ]
    for cmd_in, cmd_out in cmds:
      self.assertEqual(cmd_out, driver._PrepareCommand(cmd_in))

  def testPrepareCommandError(self):
    cmd = 123
    with self.assertRaises(error.SDKError):
      driver._PrepareCommand(cmd)


class GcloudTestDriverSDKMethodsTest(Base):

  def setUp(self):
    self.MockPopen()

    self.run_patch = self.StartObjectPatch(
        driver.SDK, 'RunGcloudRawOutput', return_value=('out', 'err', 0))

    self.sdk = self.GetSDK()
    self.expected_cwd = os.path.dirname(self.sdk_dir)
    self.popen_patch.reset_mock()

  def testRunTimeoutDisabled(self):
    self.StartObjectPatch(driver, 'TIMEOUT_ENABLED', new=False)

    self.sdk.Run('foo')
    self.assertCalledOnceWithSomeArgs(
        self.popen_patch, ['foo'],
        cwd=self.expected_cwd, env=self.environ)
    self.mock_popen.communicate.assert_called_once_with()

  def testRunTimeoutWarning(self):
    stderr = StringIO.StringIO()
    self.StartObjectPatch(sys, 'stderr', new=stderr)
    self.StartObjectPatch(driver, 'TIMEOUT_ENABLED', new=False)

    self.sdk.Run('foo', timeout=1)
    self.assertCalledOnceWithSomeArgs(
        self.popen_patch, ['foo'],
        cwd=self.expected_cwd, env=self.environ)
    self.mock_popen.communicate.assert_called_once_with()
    err_message = stderr.getvalue()
    self.assertIn('subprocess32', err_message)

  def testRunTimeout(self):
    self.StartObjectPatch(driver, 'TIMEOUT_ENABLED', new=True)

    self.sdk.Run('foo', timeout=1)
    self.assertCalledOnceWithSomeArgs(
        self.popen_patch, ['foo'],
        cwd=self.expected_cwd, env=self.environ)
    self.mock_popen.communicate.assert_called_once_with(timeout=1)

  def testRunEnv(self):
    self.StartObjectPatch(driver, 'TIMEOUT_ENABLED', new=False)
    env = {'x': 'y'}
    env.update(self.environ)

    self.sdk.Run('foo', env={'x': 'y'})
    self.assertCalledOnceWithSomeArgs(
        self.popen_patch, ['foo'],
        cwd=self.expected_cwd, env=env)
    self.mock_popen.communicate.assert_called_once_with()


class GcloudTestDriverRunGcloudTest(Base):

  def setUp(self):
    self.out = {'a': 'b', 'c': 'd'}
    self.err = 'error'
    self.code = 0

    self.run_patch = self.StartObjectPatch(
        driver.SDK, 'Run', return_value=(
            json.dumps(self.out), self.err, self.code))
    self.MockSDKFactoryDependencies()

    self.sdk = driver.DefaultSDK()

  def testRunGcloud(self):
    out, err, code = self.sdk.RunGcloud('foo')
    self.assertEqual(self.out, out)
    self.assertEqual(self.err, err)
    self.assertEqual(self.code, code)
    self.run_patch.assert_called_once_with(
        self.sdk, ['gcloud', 'foo', '--format=json'], None, None)

  def testRunGcloudTimeout(self):
    out, err, code = self.sdk.RunGcloud('foo', timeout=1)
    self.assertEqual(self.out, out)
    self.assertEqual(self.err, err)
    self.assertEqual(self.code, code)
    self.run_patch.assert_called_once_with(
        self.sdk, ['gcloud', 'foo', '--format=json'], 1, None)

  def testRunGcloudEnv(self):
    out, err, code = self.sdk.RunGcloud('foo', env={'x': 'y'})
    self.assertEqual(self.out, out)
    self.assertEqual(self.err, err)
    self.assertEqual(self.code, code)
    self.run_patch.assert_called_once_with(
        self.sdk, ['gcloud', 'foo', '--format=json'], None, {'x': 'y'})

  def testRunGcloudFormatKeys(self):
    out, err, code = self.sdk.RunGcloud('foo', format_keys=['x', 'y'])
    self.assertEqual(self.out, out)
    self.assertEqual(self.err, err)
    self.assertEqual(self.code, code)
    self.run_patch.assert_called_once_with(
        self.sdk, ['gcloud', 'foo', '--format=json(x,y)'], None, None)

  def testRunGcloudFilter(self):
    out, err, code = self.sdk.RunGcloud('foo', filters='bar')
    self.assertEqual(self.out, out)
    self.assertEqual(self.err, err)
    self.assertEqual(self.code, code)
    self.run_patch.assert_called_once_with(
        self.sdk, ['gcloud', 'foo', '--format=json', '--filter=bar'],
        None, None)

  def testRunGcloudNoOutput(self):
    self.run_patch.return_value = ('', self.err, self.code)
    out, err, code = self.sdk.RunGcloud('foo')
    self.assertEqual(None, out)
    self.assertEqual(self.err, err)
    self.assertEqual(self.code, code)
    self.run_patch.assert_called_once_with(
        self.sdk, ['gcloud', 'foo', '--format=json'], None, None)


class GcloudTestDriverRunGcloudJSONTest(Base):

  def setUp(self):
    self.MockSDKFactoryDependencies()

    self.sdk = driver.DefaultSDK()

  def PrepareOutput(self, output):
    self.out = output
    self.err = 'error'
    self.code = 0

    self.run_patch = self.StartObjectPatch(
        driver.SDK, 'RunGcloudRawOutput', return_value=(
            self.out, self.err, self.code))

  def testRunGcloudJSONOutput(self):
    self.PrepareOutput("{'a': 'b', 'c': 'd'}")

    out, _, _ = self.sdk.RunGcloud('foo')

    # Verify that the result is valid json
    json.dumps(out)

  def testRunGcloudStringOutput(self):
    self.PrepareOutput("not json")

    out, _, _ = self.sdk.RunGcloud('foo')

    # Verify that the result is valid json even though the input wasn't
    json.dumps(out)

  def testRunGcloudEmptyOutput(self):
    self.PrepareOutput("")

    out, _, _ = self.sdk.RunGcloud('foo')

    # Verify that the result is valid json even though the input wasn't
    json.dumps(out)


class GcloudTestDriverErrorTest(Base):

  def testError(self):
    expected = '.*\n.*'.join(['#foo', '123', '#out', '#err'])
    with self.assertRaisesRegexp(ValueError, expected):
      error.HandlePossibleError(('#out', '#err', 123), ValueError, '#foo')

  def testNoError(self):
    error.HandlePossibleError(('out', 'err', 0), ValueError, 'foo')


class GcloudTestDriverInstallTest(Base):

  def setUp(self):
    self.StartDictPatch(os.environ)
    self.dir_patch = self.StartObjectPatch(os.path, 'isdir', return_value=True)
    self.rm_patch = self.StartObjectPatch(shutil, 'rmtree')

    self.StartObjectPatch(_sdk_tar, 'DownloadTar', return_value='downloads')
    self.StartObjectPatch(_sdk_tar, 'UnpackTar', return_value='http://foo')

    self.MockPopen()

  def assertCalledOnceWithArgsIgnoringKwargs(self, mock_object, *expected_args):
    calls = mock_object.mock_calls

    # Assert called once
    self.assertEqual(1, len(calls))

    # Assert args matches expectation
    _, args, _ = calls[0]
    self.assertEquals(args, expected_args)

  def testInstall(self):
    driver.Init()
    root_directory = os.environ[constants.DRIVER_LOCATION_ENV]
    self.assertCalledOnceWithArgsIgnoringKwargs(self.popen_patch, [
        './install.sh', '--disable-installation-options',
        '--bash-completion=false', '--path-update=false',
        '--usage-reporting=false',
        '--rc-path={path}/.bashrc'.format(path=root_directory)])

  def testInstallAdditionalComponents(self):
    driver.Init(additional_components=['foo'])
    root_directory = os.environ[constants.DRIVER_LOCATION_ENV]
    self.assertCalledOnceWithArgsIgnoringKwargs(self.popen_patch, [
        './install.sh', '--disable-installation-options',
        '--bash-completion=false', '--path-update=false',
        '--usage-reporting=false',
        '--rc-path={path}/.bashrc'.format(path=root_directory),
        '--additional-components', 'foo'])

  def testInstallTwice(self):
    driver.Init()
    with self.assertRaises(error.InitError):
      driver.Init()

  def testNoPython(self):
    self.StartObjectPatch(sys, 'executable', new=None)
    with self.assertRaises(error.InitError):
      driver.Init()

  def testInstallFailed(self):
    self.dir_patch.return_value = False
    with self.assertRaises(error.InitError):
      driver.Init()

  def testDestroy(self):
    driver.Init()
    root_directory = os.environ[constants.DRIVER_LOCATION_ENV]
    driver.Destroy()
    self.assertNotIn(constants.DRIVER_LOCATION_ENV, os.environ)
    self.rm_patch.assert_called_once_with(root_directory)


class GcloudTestDriverDownloadTarTest(Base):

  def setUp(self):
    self.url_patch = self.StartObjectPatch(urllib2, 'urlopen', autospec=False)
    self.copy_patch = self.StartObjectPatch(shutil, 'copyfileobj')
    self.temp_dir = tempfile.mkdtemp()
    self.addCleanup(self.Cleanup)

  def Cleanup(self):
    shutil.rmtree(self.temp_dir)

  def testDownload(self):
    location = 'http://foo/bar.tar'
    download_path = _sdk_tar.DownloadTar(location, self.temp_dir)
    self.assertEqual(
        os.path.join(self.temp_dir, constants.DOWNLOAD_FOLDER, 'bar.tar'),
        download_path)
    self.url_patch.assert_called_once_with(location)

  def testDownloadTwice(self):
    location = 'http://foo/bar.tar'
    self.StartObjectPatch(os.path, 'isfile', return_value=True)
    download_path = _sdk_tar.DownloadTar(location, self.temp_dir)
    self.assertEqual(
        os.path.join(self.temp_dir, constants.DOWNLOAD_FOLDER, 'bar.tar'),
        download_path)
    self.url_patch.assert_not_called()

  def testLocalTarPath(self):
    # A local tar file doesn't need to be downloaded
    self.StartObjectPatch(os.path, 'isfile', return_value=True)
    location = os.path.join('foo', 'bar.tar')
    download_path = _sdk_tar.DownloadTar(location, self.temp_dir)
    self.assertEqual(location, download_path)
    self.url_patch.assert_not_called()

  def testBadLocalTarPath(self):
    self.StartObjectPatch(os.path, 'isfile', return_value=False)
    location = os.path.join('foo', 'bar.tar')
    with self.assertRaisesRegexp(ValueError, re.escape(location)):
      _sdk_tar.DownloadTar(location, self.temp_dir)


class GcloudTestDriverUnpackTarTest(Base):

  def setUp(self):
    self.temp_dir = tempfile.mkdtemp()
    self.addCleanup(self.Cleanup)

    self.download_path = os.path.join(
        self.temp_dir, constants.DOWNLOAD_FOLDER, 'bar.tar')
    self.repo_dir = os.path.join(self.temp_dir, constants.REPO_FOLDER)
    self.components = os.path.join(self.repo_dir, constants.COMPONENTS_FILE)
    self.installer = os.path.join(self.repo_dir, constants.INSTALLER_FILE)

    self.tar_patch = self.StartObjectPatch(tarfile, 'open')

  def Cleanup(self):
    shutil.rmtree(self.temp_dir)

  def testUnpackRepoTar(self):
    # A tar containing the entire repository will contain the components json
    # file. The resulting url should point to that file.
    self.StartObjectPatch(os.path, 'isfile', return_value=True)
    url = _sdk_tar.UnpackTar(
        self.download_path, 'http://foo/bar.tar', self.temp_dir)
    self.assertEqual('file://{0}'.format(self.components), url)
    self.tar_patch.assert_has_calls(
        [mock.call(name=self.download_path), mock.call(name=self.installer)],
        any_order=True)

  def testUnpackInstaller(self):
    # A tar only containing the installer won't contain the components json.
    # The driver shouldn't set a components url and instead let the installer
    # use its default.
    self.StartObjectPatch(os.path, 'isfile', return_value=False)
    url = _sdk_tar.UnpackTar(
        self.download_path, 'http://foo/bar.tar', self.temp_dir)
    self.assertEqual(None, url)
    self.assertEqual(
        [mock.call(name=self.download_path)], self.tar_patch.call_args_list)

  def testUnpackLocalInstallerWithComponents(self):
    # A local installer tar will need its path converted into a file url if the
    # components json is available locally.
    self.StartObjectPatch(os.path, 'isfile', side_effect=[False, True])
    url = _sdk_tar.UnpackTar(
        self.download_path, self.download_path, self.temp_dir)
    self.assertEqual(
        'file://' + os.path.join(
            os.path.dirname(self.download_path), constants.COMPONENTS_FILE),
        url)
    self.tar_patch.assert_called_with(name=self.download_path)
    for call in self.tar_patch.call_args_list:
      self.assertNotEqual(call, mock.call(name=self.installer))

  def testUnpackLocalInstallerNoComponents(self):
    # A local installer tar without the components file should return None so
    # the installer can use its baked in location for the components.
    self.StartObjectPatch(os.path, 'isfile', return_value=False)
    url = _sdk_tar.UnpackTar(
        self.download_path, self.download_path, self.temp_dir)
    self.assertEqual(None, url)
    self.tar_patch.assert_called_with(name=self.download_path)
    for call in self.tar_patch.call_args_list:
      self.assertNotEqual(call, mock.call(name=self.installer))

  def testUnpackInstallerMove(self):
    # Files are extracted into a folder to contain the repository. If this was
    # only an installer, there is no repo, so these files need to be moved up a
    # level.
    self.StartObjectPatch(os.path, 'isfile', return_value=False)
    self.StartObjectPatch(os, 'listdir', return_value=['foo'])
    move_patch = self.StartObjectPatch(shutil, 'move')
    _sdk_tar.UnpackTar(
        self.download_path, self.download_path, self.temp_dir)
    move_patch.assert_called_once_with(
        os.path.join(self.repo_dir, 'foo'), self.temp_dir)


if __name__ == '__main__':
  unittest.main()
