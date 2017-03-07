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

"""Google Cloud SDK Test Driver."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import contextlib
import copy
import json
import os
import random
import shlex
import shutil
import string
import sys
import tempfile
import types

from cloudsdk_test_driver import _config
from cloudsdk_test_driver import _sdk_tar
from cloudsdk_test_driver import constants
from cloudsdk_test_driver import error

import yaml


# We want to use the timeout feature in subprocess in Python 3.2+ or in the
# subprocess32 backport if either are available.
# pylint: disable=g-import-not-at-top
try:
  import subprocess32 as subprocess
  TIMEOUT_ENABLED = True
except ImportError:
  import subprocess
  TIMEOUT_ENABLED = hasattr(subprocess, 'TimeoutExpired')
# pylint: enable=g-import-not-at-top


class Config(_config.BaseConfig):
  """Container class for configs for an SDK.

  This class is a container for values used to configure a new SDK installation.
  These can be accessed with a dot (config.tar_location) or like a dictionary
  (config['tar_location']). The list of keys is fixed (to those in the
  DEFAULT_CONFIG) and trying to add a new key will result in a ConfigError.

  Attributes:
    environment_variables: {string: string}, Additional environment variables to
      include when running commands. Note that variables in
      LOCKED_ENVIRONMENT_VARIABLES cannot be set manually as they're used
      internally by the driver.
    service_account_email: string, The email address associated with the service
      account. This is optional as certain forms of keyfile do not require an
      account email.
    service_account_keyfile: string, The location of the service account's
      keyfile.
    project: string, The project name to run commands against.
    properties: {string: string}, gcloud properties to set before running
      commands
  """

  def __init__(self, filename=None, **kwargs):
    """Create a new Config from files and/or arguments.

    The Config is created as a clone of the DEFAULT_CONFIG. The YAML file given
    by filename is then loaded and overrides the defaults. The keyword arguments
    then override those. For example, assume the default specifies foo=1, bar=2
    and baz=3; and that file.yaml contains:
        foo: 4
        bar: 5
    Then, Config('file.yaml', foo=6) would result in foo=6, bar=5, baz=3.

    Note, new configuration values cannot be created. Only keys that already
    exist in the default can be given values. Additionally, specific
    environment variables related to the management of configurations
    cannot be set by Config.

    Arguments:
      filename: A YAML file to load config values from. Overrides defaults.
      **kwargs: Configuration values. Overrides both defaults and values from
        filename.

    Raises:
      error.ConfigError: if a locked environment variable or an invalid key is
        included in the Config.
    """
    super(Config, self).__init__()

    # Add values to dictionary in order: default, then file, then kwargs.
    self._UpdateDict(constants.DEFAULT_CONFIG)
    if filename is not None:
      self.LoadFile(filename)
    self._UpdateDict(kwargs)
    error.ValidateLockedEnvironmentVariables(self.__dict__)

  def LoadFile(self, filename):
    """Load a YAML file into this Config, overriding existing values.

    The top level of the YAML must be a dictionary. Keys in this will override
    the matching keys in this Config.

    Arguments:
      filename: string, the YAML file to load.

    Raises:
      error.ConfigError: if the YAML file fails to parse, the top level of the
        YAML file is not a dictionary or if it includes invalid keys.
    """
    with open(filename) as infile:
      try:
        config = yaml.load(infile)
      except yaml.parser.ParseError as e:
        raise error.ConfigError('Invalid config file [{file}]. {msg}'.format(
            file=filename, msg=str(e)))

    if not isinstance(config, dict):
      raise error.ConfigError('Invalid config file [{file}]. Top level is not '
                              'a dictionary.'.format(file=filename))

    error.ValidateLockedEnvironmentVariables(config)
    self._UpdateDict(config)

  def __setitem__(self, key, value):
    """Allows Config to be treated as a dictionary."""
    self.__setattr__(key, value)

  def __setattr__(self, name, value):
    """Disallows the creation of new config keys."""
    if name not in self.__dict__:
      error.RaiseInvalidKey(name)
    self.__dict__[name] = value

  def Validate(self):
    """Verify that this config would produce a valid SDK.

    Any validation that cannot be done on a partially constructed Config will be
    handled here (e.g. checking mutually exclusive options).

    Raises:
      error.ConfigError: if any of the checks fail indicating that the Config is
        invalid.
    """
    error.ValidateLockedEnvironmentVariables(self.__dict__)
    # Nothing else to do here at the moment.


# TODO(magimaster): Move this to another file.
def _IsOnWindows():
  return os.name == 'nt'


def _PrepareCommand(command):
  """Transform a command to list format."""
  if isinstance(command, types.StringTypes):
    # Need to account for the fact that shlex escapes backslashes when parsing
    # in Posix mode.
    if _IsOnWindows():
      command = command.replace(os.sep, os.sep + os.sep)
    return shlex.split(command, comments=True)

  if isinstance(command, tuple) or isinstance(command, list):
    return list(command)

  raise error.SDKError(
      'Command [{cmd}] must be a string, list or tuple.'.format(cmd=command))


# TODO(magimaster): Windows.
# TODO(magimaster): Verify that things are cleaned up if something here fails.
def Init(tar_location=None, additional_components=None, root_directory=None):
  """Downloads and installs the SDK.

  Initialize the driver by downloading and installing the SDK. This
  initialization must be done before SDK.Run will work.

  Multiple SDK objects will share this installation; however, only the version,
  installed components and installation properties (config set --installation)
  are tied to the installation.

  Args:
    tar_location: string, where to download the SDK from. If left as None, the
      latest release tar will be used.
    additional_components: [string], a list of additional components to be
      installed with the SDK.
    root_directory: string, where to download and install the SDK to. If left as
      None, a temporary folder will be created for this purpose.

  Raises:
    error.InitError: If the SDK cannot be downloaded or installed.
  """
  if _IsOnWindows():
    raise error.InitError('This driver is not currently Windows compatible.')

  # TODO(magimaster): Make sure this is usable with multiple processes.
  if constants.DRIVER_LOCATION_ENV in os.environ:
    raise error.InitError('Driver is already initialized.')

  if tar_location is None:
    tar_location = constants.RELEASE_TAR
  if root_directory is None:
    root_directory = tempfile.mkdtemp()
  elif not os.path.isdir(root_directory):
    os.makedirs(root_directory)
  else:
    os.environ[constants.DRIVER_KEEP_LOCATION_ENV] = 'True'

  # TODO(magimaster): Once some better safeguards are in place, run Destroy if
  # anything in Init fails.
  download_path = _sdk_tar.DownloadTar(tar_location, root_directory)

  snapshot_url = _sdk_tar.UnpackTar(download_path, tar_location, root_directory)
  env = {}
  if snapshot_url:
    env[constants.SNAPSHOT_ENV] = snapshot_url

  if sys.executable:
    env[constants.PYTHON_ENV] = sys.executable
  # TODO(magimaster): Document that environment will override these.
  env.update(copy.deepcopy(os.environ))

  if constants.PYTHON_ENV not in env:
    raise error.InitError('Neither sys.executable nor the {var} '
                          'environment variable are set.'.format(
                              var=constants.PYTHON_ENV))

  sdk_dir = os.path.join(root_directory, constants.SDK_FOLDER)
  command = [
      './install.sh',
      '--disable-installation-options',
      '--bash-completion=false',
      '--path-update=false',
      '--usage-reporting=false',
      '--rc-path={path}/.bashrc'.format(path=root_directory)]
  if additional_components:
    if isinstance(additional_components, types.StringTypes):
      raise error.InitError(
          'additional_components must be an iterable of strings.')
    command.append('--additional-components')
    command.extend(additional_components)

  p = subprocess.Popen(
      command, stdout=subprocess.PIPE,
      stderr=subprocess.PIPE, cwd=sdk_dir, env=env)
  out, err = p.communicate()
  error.HandlePossibleError((out, err, p.returncode),
                            error.InitError, 'SDK installation failed')

  if not os.path.isdir(sdk_dir):
    raise error.InitError(
        'SDK installation failed. SDK directory was not created.')

  # Store this as an environment variable so subprocesses will have access. Set
  # this last so that a failed installation won't permit the creation of SDK
  # objects.
  os.environ[constants.DRIVER_LOCATION_ENV] = root_directory


def Destroy():
  """Remove the SDK installation."""
  # TODO(magimaster): Windows.
  # TODO(magimaster): Add some safeguards here.
  root_directory = os.getenv(constants.DRIVER_LOCATION_ENV)
  keep_location = os.getenv(constants.DRIVER_KEEP_LOCATION_ENV)

  if root_directory is not None:
    if os.path.isdir(root_directory) and not keep_location:
      shutil.rmtree(root_directory)
    os.environ.pop(constants.DRIVER_LOCATION_ENV)

  if keep_location is not None:
    os.environ.pop(constants.DRIVER_KEEP_LOCATION_ENV)


@contextlib.contextmanager
def Manager(*args, **kwargs):
  """A simple context manager to initialize and destroy the driver."""
  try:
    Init(*args, **kwargs)
    yield
  finally:
    Destroy()


class SDK(object):
  """Represents an installed, configured SDK.

  Used to run commands against the SDK. Note that once configured the SDK cannot
  be changed. To change configurations, create a new SDK object. This code will
  handle the management of configurations and any differences between two SDKs
  created with the same configs should be invisible to the user.

  If needed, SDK tar files are downloaded to the directory specified in the
  GCLOUD_TEST_DRIVER_DOWNLOADS environment variable, if it exists; otherwise,
  they're downloaded to an sdk_downloads subfolder in the system temporary
  directory (tempfile.gettempdir()).

  Attributes:
    config: ImmutableConfig, an immutable copy of the Config used to create this
      SDK. Note that Run commands don't necessarily use these values unchanged
      as some internal details may require altering these.
  """

  def __init__(self, config, sdk_dir, config_name, environ):
    """Create a new SDK from a Config.

    Note: This constructor should not be called directly. Instead, use one of
    the factory functions, such as driver.DefaultSDK or driver.SDKFromArgs.

    Args:
      config: Config, the configuration to use with this SDK object.
      sdk_dir: string, the path to the SDK installation folder.
      config_name: string, the name of the configuration to create.
      environ: {string: ...}, the environment variables to use when running
        commands with this SDK object. This should be similar to
        config.environment_variables, but not necessarily the same.
    """
    config.Validate()

    self.config = _config.ImmutableConfig(config)

    self._sdk_dir = sdk_dir
    self._config_name = config_name
    self._env = environ

  def RunInitializationCommands(self):
    """Runs several gcloud commands to finish setting up an SDK."""
    if self.config.service_account_keyfile:
      # Activating a service account should also set this to the active account.
      command = ['auth', 'activate-service-account']
      if self.config.service_account_email:
        command.append(self.config.service_account_email)
      command.extend(['--key-file', self.config.service_account_keyfile])
      result = self.RunGcloudRawOutput(command)
      error.HandlePossibleError(
          result, error.SDKError, 'Activating service account failed')

    # Set project.
    if self.config.project:
      command = ['config', 'set', 'project', self.config.project]
      result = self.RunGcloudRawOutput(command)
      error.HandlePossibleError(
          result, error.SDKError, 'Setting project failed')

    # Set properties.
    if self.config.properties:
      for key, value in self.config.properties.items():
        command = ['config', 'set', key, value]
        result = self.RunGcloudRawOutput(command)
        error.HandlePossibleError(
            result, error.SDKError,
            'Setting property [{prop}] failed'.format(prop=key))

  def Run(self, command, timeout=None, env=None):
    """Run a command against this SDK installation.

    Args:
      command: string, list or tuple, The command to run (e.g. ['gsutil', 'cp',
        ...])
      timeout: number, Seconds to wait before timing out the command.
      env: dict or None, Extra environmental variables use with this command.

    Returns:
      (stdout, stderr, returncode) returned from the command.

    Raises:
      error.SDKError: If the command cannot be run.
    """
    # Add the passed in variables to the precomputed environment (without
    # altering either dictionary).
    if env:
      env = dict(self._env, **env)
    else:
      env = self._env

    p = subprocess.Popen(
        _PrepareCommand(command), stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, cwd=os.path.dirname(self._sdk_dir), env=env)
    if TIMEOUT_ENABLED:
      out, err = p.communicate(timeout=timeout)
    else:
      if timeout:
        sys.stderr.write(
            'Warning: timeout specified, but subprocess32 is not available.')
      out, err = p.communicate()

    # TODO(magimaster): Change this to raise an error if returncode isn't 0
    return out, err, p.returncode

  def RunGcloud(self, command, format_keys=None,
                filters=None, timeout=None, env=None):
    """Run a gcloud command against this SDK installation.

    Args:
      command: string, list or tuple, The gcloud command to run (no need to
        start with 'gcloud').
      format_keys: list, Keys to pass in as part of a format specification (the
        format will be json).
      filters: string, Filters to pass to the gcloud command.
      timeout: number, Seconds to wait before timing out the command.
      env: dict or None, Extra environmental variables use with this command.

    Returns:
      (json_output, stderr, returncode) where json_output is the json output
      (using --format=json) parsed into a python object.

    Raises:
      error.SDKError: If the command cannot be run or returns something that
        cannot be parsed.
    """
    if format_keys:
      formats = 'json({keys})'.format(keys=','.join(format_keys))
    else:
      formats = 'json'

    out, err, code = self.RunGcloudRawOutput(
        command, formats, filters, timeout, env)

    if out:
      try:
        return json.loads(out), err, code
      except ValueError:
        # TODO(magimaster): Log failure to decode JSON when logging is added
        return out, err, code
    else:
      return None, err, code

  def RunGcloudRawOutput(self, command, formats=None, filters=None,
                         timeout=None, env=None):
    """Runs a gcloud command and returns the raw text output.

    Args:
      command: string, list or tuple, The gcloud command to run (no need to
        start with 'gcloud').
      formats: string, Formats to pass to the gcloud command.
      filters: string, Filters to pass to the gcloud command.
      timeout: number, Seconds to wait before timing out the command.
      env: dict or None, Extra environmental variables use with this command.

    Returns:
      (stdout, stderr, returncode) returned from the command.

    Raises:
      error.SDKError: If the command cannot be run.
    """
    command = ['gcloud'] + _PrepareCommand(command)

    if formats:
      command.append('--format={fmt}'.format(fmt=formats))
    if filters:
      command.append('--filter={flt}'.format(flt=filters))

    out, err, ret = self.Run(command, timeout, env)

    return out, err, ret


def SDKFromConfig(config):
  """Create an SDK from a config. This is the main factory for SDK objects.

  Args:
    config: Config, The Config object to use in creating the SDK.

  Returns:
    SDK, The configured SDK object.

  Raises:
    error.SDKError: If anything went wrong during creation of the SDK.
  """
  driver_location = os.getenv(constants.DRIVER_LOCATION_ENV)
  if driver_location is None:
    raise error.SDKError('Unable to locate the SDK. Make sure Init was '
                         'called before creating SDK objects.')

  # Generate a random name for this configuration.
  config_name_length = 14
  rng = random.SystemRandom()
  config_name = ''.join(['config'] + [
      rng.choice(string.ascii_lowercase + string.digits)
      for _ in range(config_name_length - len('config'))])

  # Prepare the environment variables.
  sdk_dir = os.path.join(driver_location, constants.SDK_FOLDER)
  environ = _config.PrepareEnviron(
      config.environment_variables, config_name, sdk_dir)

  # Create and initialize the sdk.
  sdk = SDK(config, sdk_dir, config_name, environ)
  sdk.RunInitializationCommands()
  return sdk


def DefaultSDK():
  return SDKFromConfig(Config())


def SDKFromFile(filename):
  return SDKFromConfig(Config(filename=filename))


def SDKFromDict(dictionary):
  return SDKFromConfig(Config(**dictionary))


def SDKFromArgs(**kwargs):
  return SDKFromConfig(Config(**kwargs))
