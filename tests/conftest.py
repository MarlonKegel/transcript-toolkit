"""NiceGUI ships a pytest harness that drives the app's pages in-process; loading its plugin
here is what gives tests the `user` fixture. It only adds fixtures — tests that never ask for
them are unaffected."""
pytest_plugins = ["nicegui.testing.user_plugin"]
