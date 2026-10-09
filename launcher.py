"""PyInstaller entry point that imports the application as a package."""

from camp_vision.app import main


if __name__ == "__main__":
    raise SystemExit(main())
