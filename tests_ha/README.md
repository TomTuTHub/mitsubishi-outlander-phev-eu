Tests gegen echtes Home Assistant (pytest-homeassistant-custom-component, Python >= 3.14):

    python -m pytest -c tests_ha/pytest.ini --rootdir . tests_ha -p no:cacheprovider

Die Stub-Tests in tests/ laufen getrennt (ohne HA-Plugin):

    python -m pytest -p no:homeassistant tests
