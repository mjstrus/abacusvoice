from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

setup(
    name="abacus_voice",
    version="0.1.0",
    description="Moduł automatycznych rozmów telefonicznych dla Abacus Centrum Księgowe",
    author="Abacus Centrum Księgowe",
    author_email="kontakt@abacus24.pl",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
)
