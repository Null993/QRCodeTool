import sys


if __name__ == "__main__":
    if "--package-self-test" in sys.argv:
        from qrcap.selftest import run_package_self_test

        raise SystemExit(run_package_self_test())

    from qrcap.app import run

    raise SystemExit(run())
