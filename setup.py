import setuptools

setuptools.setup(
    name="nbcull",
    version='0.0.1',
    url="https://github.com/data-8/nbcull",
    author="Data 8 @ UC Berkeley",
    description="Shuts down a user notebook if it has been inactive for too long.",
    packages=setuptools.find_packages(),
    install_requires=[
        'notebook', 'tornado', 'traitlets'
    ],
    package_data={'nbcull': ['static/*']},
)
