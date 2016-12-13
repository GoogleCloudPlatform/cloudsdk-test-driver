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

"""Constants used by the driver."""

# The default configuration. Also specifies what keys are valid in a config.
# Leave project, etc. as None to leave these values unset in the configured SDK.
DEFAULT_CONFIG = {
    'environment_variables': {
        'CLOUDSDK_CORE_DISABLE_PROMPTS': '1',
    },
    'service_account_email': None,
    'service_account_keyfile': None,
    'project': None,
    'properties': {},
}


# The default tar to download.
RELEASE_TAR = ('https://dl.google.com/dl/cloudsdk/channels/'
               'rapid/google-cloud-sdk.tar.gz')


# Environment variable name constants.
DRIVER_LOCATION_ENV = 'CLOUDSDK_DRIVER_LOCATION'
DRIVER_KEEP_LOCATION_ENV = 'CLOUDSDK_DRIVER_KEEP_LOCATION'
SNAPSHOT_ENV = 'CLOUDSDK_COMPONENT_MANAGER_SNAPSHOT_URL'
PYTHON_ENV = 'CLOUDSDK_PYTHON'
CONFIG_ENV = 'CLOUDSDK_CONFIG'
PYTHON_PATH = 'PYTHONPATH'


# Static filenames.
COMPONENTS_FILE = 'components-2.json'
INSTALLER_FILE = 'google-cloud-sdk.tar.gz'


# Static directory names.
SDK_FOLDER = 'google-cloud-sdk'
REPO_FOLDER = 'repo'
DOWNLOAD_FOLDER = 'downloads'
BIN_FOLDER = 'bin'


# These environment variables can't be set by the user as they're used
# internally by the driver.
LOCKED_ENVIRONMENT_VARIABLES = [
    CONFIG_ENV,
    DRIVER_LOCATION_ENV,
]
