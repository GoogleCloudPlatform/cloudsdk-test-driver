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

"""Classes and helper functions supporting Config."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import copy
import hashlib
import json
import os
import sys

from cloudsdk_test_driver import constants
from cloudsdk_test_driver import error


class BaseConfig(object):
  """Common functionality of Config and ImmutableConfig.

  This is not meant to be subclassed by anything other than Config and
  ImmutableConfig.

  Attributes:
    See Config for a list of attributes.
  """

  def _UpdateDict(self, dictionary):
    """Validate keys and update internal dictionary."""
    for key in dictionary:
      if key not in constants.DEFAULT_CONFIG:
        error.RaiseInvalidKey(key)
    self.__dict__.update(copy.deepcopy(dictionary))

  def keys(self):  # pylint: disable=invalid-name
    """Allows configs to be treated as a dictionary."""
    return self.__dict__.keys()

  def __len__(self):
    """Allows configs to be treated as a dictionary."""
    return len(self.__dict__)

  def __getitem__(self, key):
    """Allows configs to be treated as a dictionary."""
    return self.__dict__[key]

  def __iter__(self):
    """Allows configs to be treated as a dictionary."""
    return iter(self.keys())


class ImmutableConfig(BaseConfig):
  """An immutable configuration.

  When an SDK is created, it stores an ImmutableConfig containing the
  configuration values used to create it. These cannot be changed as doing so
  would only result in the values being out of sync with the SDK.

  Note that while it is technically possible to make changes to, for example,
  the environment variables within an ImmutableConfig, it will generally
  result in undefined behavior.

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
      commands.

  Raises:
    error.ConfigError: if something tries to mutate it.
  """

  def __init__(self, config):
    super(ImmutableConfig, self).__init__()
    self._UpdateDict(config.__dict__)

  def __setitem__(self, unused_key, unused_value):
    raise error.ConfigError('ImmutableConfig object is immutable')

  def __setattr__(self, unused_name, unused_value):
    raise error.ConfigError('ImmutableConfig object is immutable')

  def _Key(self):
    return json.dumps(self.__dict__, sort_keys=True)

  def __hash__(self):
    digest = hashlib.md5(self._Key()).hexdigest()
    return int(digest, 16)

  def __eq__(self, other):
    # pylint: disable=protected-access
    return isinstance(other, ImmutableConfig) and self._Key() == other._Key()


def PrepareEnviron(user_environ, config_name, sdk_dir):
  """Prepare environmental variables for use by SDK objects.

  Takes an evironment variable dictionary and a couple of extra parameters and
  rearranges things to make sure everything is in place for the creation of an
  SDK object.

  Args:
    user_environ: {string: ...}, a dictionary of environment variables.
    config_name: string, the internal name for the gcloud configuration being
      created.
    sdk_dir: string, the directory the SDK was installed to.

  Returns:
    {string, ...}: the updated environment variables.

  Raises:
    error.SDKError: if the environment variables cannot be rearranged into a
      usable state (e.g. if no Python executable can be found).
  """
  # Make a copy to prevent changes to the original
  environ = copy.deepcopy(user_environ)

  # Make sure the sdk bin folder is first on the path and add the $PATH
  # environment variable if it isn't already included. This way, local changes
  # to the PATH will still be available to the commands run later as they're
  # otherwise run in an isolated subprocess with a clean environment. This is
  # needed for commands that reference external programs.
  bin_folder = os.path.join(sdk_dir, constants.BIN_FOLDER)
  path_components = [bin_folder]
  if 'PATH' in environ:
    path_components.append(environ['PATH'])
  if 'PATH' not in environ or os.environ['PATH'] not in environ['PATH']:
    path_components.append(os.environ['PATH'])
  environ['PATH'] = os.pathsep.join(path_components)

  # Point to this configuration's config directory.
  environ[constants.CONFIG_ENV] = os.path.join(sdk_dir, config_name)

  # Point to a consistent version of python.
  if constants.PYTHON_ENV not in environ:
    if not sys.executable:
      raise error.SDKError('Neither sys.executable nor the {var} '
                           'environment variable are set.'.format(
                               var=constants.PYTHON_ENV))
    environ[constants.PYTHON_ENV] = sys.executable

  # Make sure any changes to sys.path are reflected in subprocesses.
  if constants.PYTHON_PATH not in environ:
    environ[constants.PYTHON_PATH] = os.pathsep.join(sys.path)
  else:
    environ[constants.PYTHON_PATH] = os.pathsep.join(
        [environ[constants.PYTHON_PATH]] + sys.path)

  return environ
