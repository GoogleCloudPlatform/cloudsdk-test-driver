# Cloud SDK Test Driver

The Cloud SDK Test Driver is a utility to make it easier to write and run tests
that make use of the Cloud command line utilities. The driver handles
downloading, installing, configuring, running commands on and deleting the SDK.

[TOC]

## Design goals

The test driver is designed to be easily usable in any test environment. In
particular, it should 'just work' even if run in multiple test processes at
once (such as when using pytest's xdist plugin), at least as far as the backends
the commands communicate with allow.

For this reason, the SDK objects are immutable. Once an SDK object is created,
its configuration is set. This way, any tests sharing that SDK object can be
sure they won't interfere with each other. However, SDK objects are fairly
lightweight, so there should be little overhead even if every test creates its
own SDK object. (An SDK object roughly corresponds to a gcloud configuration.)

Additionally, the driver and its classes are not intended to be subclassed. Test
suite specific setup (for example) should be handled with the test's setUp or
setUpClass functions instead.

## Usage

The basic usage pattern for the test driver is:

1. Import the driver

1. Initialize the driver

1. Create an SDK object

1. Run commands against the SDK

1. Destroy the driver

### Importing the driver

The only file that needs to be imported is driver.py. Everything needed to use
the driver should be available through that import.

### Initializing the driver

Initialization is done by calling `driver.Init()`. This needs to be done exactly
once before any SDK objects are created. If there are multiple processes, this
should be done in the main process before spawning the child processes. For most
tests, `driver.Manager()` makes this simple.

```python
if __name__=='__main__':
  with driver.Manager():
    main()
```

If there's not a good place to use a context manager, `driver.Init()` should be
called in the main setup, and `driver.Destroy()` should be called in the main
teardown. For example, using pytest's hooks:

```python
def pytest_configure(config):
  driver.Init()

def pytest_unconfigure(config):
  driver.Destroy()
```

The default parameters to Init and Manager will download and install the latest
release SDK. (This is currently limited to Linux. See b/30482152.) Parameters
are available to change which tar is downloaded, which additional components to
install, and where to install the SDK to. (Since the driver usually uses the
release version, alpha and beta commands will not be available by default.
Include them in the additional components if any tests will need them.)

Note that the passed in root_directory will be deleted by Destroy, so be careful
what folder is used here.

```python
driver.Init(tar_location='~/personal_build.tar',
            additional_components=['alpha'],
            root_directory='~/sdk')
```

### Create an SDK object

#### Configurations

All methods of creating an SDK ultimately create and populate a Config object.
Config is limited to the keys present in constants.DEFAULT_CONFIG. These are:

* environment_variables - Environment variables to be set before running
  commands. Defaults to the dictionary {'CLOUDSDK_CORE_DISABLE_PROMPTS': '1'}.

* service_account_email - The email address associated with a service account.
  Defaults to None.

* service_account_keyfile - The path to the JSON key file associated with a
  service account. Defaults to None.

* project - The project to be used for running commands. Defaults to None.

* properties - gcloud properties to be set before running commands. Defaults to
  an empty dictionary.

#### driver.DefaultSDK

The simplest way to get an SDK object is to call `driver.DefaultSDK()`. As the
name suggests, this returns a new SDK object created using the default
configuration. If you want to change anything, you'll need to use one of the
other options.

#### driver.SDKFromArgs

If you want to make a simple, one-off change, `driver.SDKFromArgs` allows you
to just pass in the config as an argument. All details not specifically changed
will be taken from the default config.

```python
sdk = driver.SDKFromArgs(project='foo_test_project')
```

#### driver.SDKFromDict

Similarly, `driver.SDKFromDict` will take differences from a dictionary instead.

```python
cfg = {'project': 'foo_test_project'}
sdk = driver.SDKFromDict(cfg)
```

#### driver.SDKFromFile

If you use a common configuration across several test files, you can also store
your config in a YAML file and create an SDK object from that using
`driver.SDKFromFile`. Again, anything not specifically changed will be taken
from the default config.

```yaml
# foo_test.yaml
project: foo_test_project
service_account_email: foo@example.com
service_account_keyfile: foo_key.json
```

```python
# foo_test.py
sdk = driver.SDKFromFile('foo_test.yaml')
```

#### driver.SDKFromConfig

Finally, if you want to use some combination of these, or you want to create a
series of SDK objects with small differences between the configurations, you can
create a `driver.Config` object, set each attribute as needed, and create SDK
objects from that.

```python
config = driver.Config('foo_base.yaml', project='foo_test_{}_project'.format(n))
config.environment_variables.update({'TEST_NUMBER': n})
# or config['environment_variables']... if you prefer
sdk = driver.SDKFromConfig(config)
```

#### sdk.config

Once created, `sdk.config` stores an immutable copy of the Config used to create
it. This means it's safe to change the Config object used to create the SDK.

Note that while the ImmutableConfig object tries to live up to its name, Python
makes that an almost impossible goal. It is possible to alter sdk.config, but
doing so will only result in sdk.config being out of sync with the gcloud
configuration it should be tied to. See below for more information on what to do
if you need to test configuration changes.

Also, be aware that commands run against an SDK object do not necessarily use
the contents of `sdk.config` as is. In particular, several environment variables
are altered for internal reasons. (Generally speaking, things in `config` should
take precedence though.)

### Run commands against the SDK

The basic function here is `sdk.RunGcloud`, or `sdk.Run` for cloud utilities
other than gcloud.

#### sdk.RunGcloud

`RunGcloud` takes a command (as a list or a string), runs it through gcloud, and
parses the output into an object. It returns the parsed output, anything written
to stderr, and the return code of the command.

```python
out, err, code = sdk.RunGcloud(['config', 'list'])
if code == 0:
  print('Current account: {}'.format(out['core']['account']))
else:
  print('Error: {}'.format(err))
```

`RunGcloud` also accepts parameters to pass to gcloud's format and filter flags.
Note that RunGcloud forces the format to be json, so it only accepts a list of
keys to format rather than a full format string. (`RunGcloudRawOutput` does not
parse the output and accepts a full format string.) See `gcloud topic formats`
and `gcloud topic filters` for more information on what can be done with these
parameters.

```python
out, _, _ = sdk.RunGcloud(['compute', 'instances', 'list'],
                          format_keys=['name', 'status'], filters='name:foo*')
print(out)
```

This function also accepts a timeout parameter (in seconds). This requires
subprocess32 to function and will print a warning and ignore the timeout if it
is not available.

It also accepts a dictionary of extra environmental variables to use for this
one command. Values in this dictionary will override those in the configuration.

```
_, _, code = sdk.RunGcloud(['compute', 'foo'], env={'FOO_TEST': 1})
self.assertEqual(0, code)
```

#### sdk.Run

For commands using other Cloud SDK utilities, `Run` can be used. This accepts a
command, timeout and environment in the same format as `RunGcloud` but can't use
the format and filter parameters. It returns the stdout, stderr and return code
of the command in the same way `RunGcloudRawOutput` does. (It doesn't attempt
to parse the output.)

```python
out, _, _ = sdk.Run(['gsutil', 'ls', my_bucket])
print(out)
```

### Destroy the driver

At the end of the test suite, once all tests have finished, the driver can be
destroyed by calling `driver.Destroy`. This will delete the installation folder
(whatever was passed in as root_directory in Init, or the temporary folder it
created if no root_directory was given) freeing up the disk space. All SDK
objects created before this will no longer function.

After `Destroy`, `Init` can be called again to reinstall the SDK, possibly from
a different tar file, or with different components, though it would usually be
better to do that in a separate test suite instead.

## Writing tests with the driver

### Testing if a command runs

The simplest test is to check if a particular command runs at all. Just running
the command and checking that it exited with a 0 return code might be enough.

```python
_, _, code = sdk.RunGcloud(my_command)
self.assertEqual(0, code)
```

### CRUD test

Testing an interdependent sequence of commands isn't much harder. `RunGcloud`
parses the output into an object, which makes comparisons on that output easy.
It is usually preferable to make each step an independent test, but for the
purposes of demonstration (and because it depends on which testing framework is
being used) that is not done here.

```python
# Create an instance
create_output, _, code = sdk.RunGcloud(['compute', 'instances', 'create', name])
self.assertEqual(0, code)

# Wait on the results to propagate
while True:
  list_output, _, _ = sdk.RunGcloud(['compute', 'instances', 'list']
                                    filters='name={name}'.format(name=name))
  if len(list_output) > 0:
    break
  time.sleep(5)

# Add a tag
_, _, code = sdk.RunGcloud(
    ['compute', 'instances', 'add-tags', '--tags', 'FOO'])

# Verify it was added
describe_output, _, code = sdk.RunGcloud(
    ['compute', 'instances', 'describe', name])
self.assertEqual(0, code)
self.assertIn('FOO', describe_output['tags'])

# Delete the instance
_, _, code = sdk.RunGcloud(['compute', 'instances', 'delete', name])
self.assertEqual(0, code)
```

### Testing configuration changes

A common pattern is to run a command, change some configuration and run it
again. Doing this with the immutable SDK objects might seem difficult, but there
are a few ways around this.

#### The safe way

The safest way is to simply use a second SDK object and run the command once
against each object. Since SDK objects are fairly light weight, this shouldn't
add much overhead. This method is also thread safe even if multiple tests
sharing these objects run in parallel.

```python
foo_1_sdk = driver.SDKFromArgs(properties={'compute/foo': '1'})
foo_2_sdk = driver.SDKFromArgs(properties={'compute/foo': '2'})

_, _, code = foo_1_sdk.RunGcloud(['compute', 'foo'])
self.assertEqual(0, code)

_, error, code = foo_2_sdk.RunGcloud(['compute', 'foo'])
self.assertNotEqual(0, code)
self.assertIn('invalid foo', error)
```

#### The simple way

For certain short-lived changes, environment variables can be used to change the
configuration on a command-by-command basis.

```python
sdk = driver.SDKFromArgs(properties={'compute/foo': '1'})

_, _, code = sdk.RunGcloud(['compute', 'foo'])
self.assertEqual(0, code)

_, error, code = sdk.RunGcloud(['compute', 'foo'], env={
    'CLOUDSDK_COMPUTE_FOO': '2'})
self.assertNotEqual(0, code)
self.assertIn('invalid foo', error)
```


#### The intuitive way

Using multiple SDK objects can be somewhat less readable and less obvious. While
it's not recommended, it is possible to change the configuration of an SDK
object by running `gcloud config` commands. Doing so will mean that the
`sdk.config` and the actual configuration being used will be out of sync, and
calling these commands on an SDK object used by more than one test can cause
hard-to-diagnose errors (so don't do it).

```python
sdk = driver.SDKFromArgs(properties={'compute/foo': '1'})

_, _, code = sdk.RunGcloud(['compute', 'foo'])
self.assertEqual(0, code)

sdk.RunGcloud(['config', 'set', 'compute/foo', '2'])
# Note that sdk.config.properties['compute/foo'] is still '1'

_, error, code = sdk.RunGcloud(['compute', 'foo'])
self.assertNotEqual(0, code)
self.assertIn('invalid foo', error)
```

