import logging


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("Artifact")


# this is the initial module of your app
# this is executed whenever some client-code is calling `import Artifact` or `from Artifact import ...`
# put your main classes here, eg:
class MyClass:
    def my_method(self):
        return "Hello World"


def main():
    # this is the main module of your app
    # it is only required if your project must be runnable
    # this is the script to be executed whenever some users writes `python -m Artifact` on the command line, eg.
    x = MyClass().my_method()
    print(x)


# let this be the last line of this file
logger.info("Artifact loaded")
