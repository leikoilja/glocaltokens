from setuptools import find_packages, setup

with open("README.md") as readme_file:
    README = readme_file.read()

with open("HISTORY.md") as history_file:
    HISTORY = history_file.read()

setup_args = dict(
    name="glocaltokens",
    version="0.2.0",
    description="Tool to extract Google device local authentication tokens in Python",
    long_description_content_type="text/markdown",
    long_description=README + "\n\n" + HISTORY,
    license="MIT",
    packages=find_packages(),
    include_package_data=True,
    author="Ilja Leiko",
    author_email="leikoilja@gmail.com",
    keywords=["Google", "Google Home", "Authentication", "LocalAuthenticationTokens"],
    url="https://github.com/leikoilja/glocaltokens",
    download_url="https://pypi.org/project/glocaltokens/",
)

install_requires = [
    "uuid",
    "gpsoauth",
    # grpcio is pinned by HomeAssistant
    # See https://github.com/home-assistant/core/blob/6e67b943da09a13409e1a61ec34ed7144e1093c3/script/gen_requirements_all.py
    "grpcio==1.31.0",
    "grpcio-tools",
    "simplejson",
    "requests",
    "zeroconf",
]

if __name__ == "__main__":
    setup(**setup_args, install_requires=install_requires)
