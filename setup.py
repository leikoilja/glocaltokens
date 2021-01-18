from setuptools import setup, find_packages

with open('README.md') as readme_file:
    README = readme_file.read()

with open('HISTORY.md') as history_file:
    HISTORY = history_file.read()

setup_args = dict(
    name='glocaltokens',
    version='0.1.2',
    description='Tool to extract Google device local authentication tokens in Python',
    long_description_content_type="text/markdown",
    long_description=README + '\n\n' + HISTORY,
    license='MIT',
    packages=find_packages(),
    include_package_data=True,
    author='Ilja Leiko',
    author_email='leikoilja@gmail.com',
    keywords=['Google', 'Authentication', 'LocalAuthenticationTokens'],
    url='https://github.com/leikoilja/glocaltokens',
    download_url='https://pypi.org/project/glocaltokens/',
)

install_requires = [
    'gpsoauth',
    'grpcio',
    'grpcio-tools',
    'jq',
    'simplejson',
    'requests',
]

if __name__ == '__main__':
    setup(**setup_args, install_requires=install_requires)
