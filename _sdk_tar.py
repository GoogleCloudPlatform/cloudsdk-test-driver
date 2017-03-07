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

"""Handle downloading and unpacking the SDK tar file."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import shutil
import tarfile
import urllib2
import urlparse

from cloudsdk_test_driver import constants
from cloudsdk_test_driver import error


# TODO(magimaster): Verify that unusual conditions don't result in bad behavior.


# TODO(magimaster): Make sure this behavior is covered in documentation.
def DownloadTar(tar_location, download_directory):
  """Downloads the given tar if needed.

  If tar_location is a url, download the requested file. If the file already
  exists, it won't download it again.

  If tar_location is a local path, verify it exists and then return the path
  unchanged (no need to make another copy of the file).

  Args:
    tar_location: string, URL or path to the tar file.
    download_directory: string, path to download to.

  Returns:
    string, The local path of the tar file.

  Raises:
    error.InitError: If there was a problem when downloading the file.
    ValueError: If tar_location is a local file that does not exist.
  """
  url_parts = urlparse.urlsplit(tar_location)

  # Check if the tar file points to something that needs to be downloaded.
  # TODO(magimaster): Make things downloadable from gs:// (?).
  # TODO(magimaster): Retry failed downloads.
  if url_parts.scheme:
    # Prepare the download directory.
    download_directory = os.path.join(
        download_directory, constants.DOWNLOAD_FOLDER)
    if not os.path.exists(download_directory):
      os.makedirs(download_directory)

    tar_name = os.path.basename(url_parts.path)
    # TODO(magimaster): Make sure this all works with multiple processes.
    download_path = os.path.join(download_directory, tar_name)
    # Don't redownload the same file if it already exists.
    if not os.path.isfile(download_path):
      try:
        req = urllib2.urlopen(tar_location)
        with open(download_path, 'wb') as fp:
          shutil.copyfileobj(req, fp)
      except urllib2.URLError as err:
        error.RaiseTarError('downloading', tar_location, err.reason)
      except shutil.Error as err:
        error.RaiseTarError('downloading', tar_location, err.message)
    return download_path
  else:
    # Tar location points to a local directory. Verify it exists and return it.
    if not os.path.isfile(tar_location):
      raise ValueError('[{tar}] does not exist'.format(tar=tar_location))
    return tar_location


def ExtractWithoutOverwrite(tar, directory):
  """Extract an open tar to directory without overwriting existing files."""
  for member in tar.getmembers():
    if member.isfile() and os.path.isfile(os.path.join(directory, member.name)):
      # This file already exists. Don't overwrite it.
      continue
    tar.extract(member, path=directory)


def UnpackTar(download_path, tar_location, root_directory):
  """Unpacks the tar file and the installer if needed.

  Unpacks the given tar file and checks whether it was a tar of the full repo or
  just the installer. For the full repo, further unpack the installer and return
  the components json with it. For a lone installer, unpack it and return a url
  pointing to the components json located at the original tar location.

  Args:
    download_path: string, Path to the tar file to unpack.
    tar_location: string, the original location of the tar file.
    root_directory: string, path to install to.

  Returns:
    string, the URL for the components json for this installation or None if
      the installer should use its default location for the components.

  Raises:
    error.InitError: if something went wrong when unpacking the tar.
  """
  # TODO(magimaster): Windows.
  # TODO(magimaster): Make sure paths work with multiple installs/threads.
  repo_directory = os.path.join(root_directory, constants.REPO_FOLDER)
  if not os.path.exists(repo_directory):
    os.makedirs(repo_directory)
  try:
    with tarfile.open(name=download_path) as tar:
      ExtractWithoutOverwrite(tar, repo_directory)
  except tarfile.TarError as err:
    error.RaiseTarError('extracting', download_path, err.message)

  # TODO(magimaster): Make sure documentation covers this carefully.
  # If there's a components json file in the tar, assume it's a full repo.
  # Otherwise, assume it's only an installer.
  components_json = os.path.join(repo_directory, constants.COMPONENTS_FILE)
  if os.path.isfile(components_json):
    # tar_location pointed to a repo tar. Extract the installer and return a url
    # to the components json from the repo.
    snapshot_url = 'file://{path}'.format(path=components_json)
    try:
      with tarfile.open(
          name=os.path.join(repo_directory, constants.INSTALLER_FILE)) as tar:
        ExtractWithoutOverwrite(tar, root_directory)
    except tarfile.TarError as err:
      error.RaiseTarError('extracting', download_path, err.message)
  else:
    # tar_location pointed to an installer tar. If the tar_location was a local
    # path, try and find the corresponding component file. (Particularly, if
    # someone unzipped a repo tar and tried to use the installer from within
    # that.) Otherwise, leave the components location unset and let the
    # installer use the default.
    # TODO(magimaster): This probably misses a few corner cases.
    url_parts = urlparse.urlparse(tar_location)
    if not url_parts.scheme:  # Local path
      components_json = os.path.join(
          os.path.dirname(tar_location), constants.COMPONENTS_FILE)
      if os.path.isfile(components_json):
        snapshot_url = urlparse.urljoin('file://', components_json)
      else:
        snapshot_url = None
    else:
      snapshot_url = None

    # This wasn't a repo, so move the files up a level for consistency.
    try:
      for filename in os.listdir(repo_directory):
        if not os.path.exists(os.path.join(root_directory, filename)):
          shutil.move(os.path.join(repo_directory, filename), root_directory)
    except (OSError, shutil.Error) as err:
      error.RaiseTarError('extracting', download_path, err.message)

  return snapshot_url
