======
Typing
======

oslo.versionedobjects ships a mypy plugin that improves type checking of
projects that use oslo.versionedobjects.

.. note::

   The plugin is a temporary solution pending a larger rework. It is only
   supported when used with the mypy type checker.

Enabling the plugin
-------------------

To enable the plugin, add the following to your ``pyproject.toml``:

.. code-block:: toml

   [tool.mypy]
   plugins = ["oslo_versionedobjects.mypy"]

What the plugin does
--------------------

oslo.versionedobjects dynamically generates attributes on versioned object
classes from the ``fields`` dict defined in the class body. This means mypy
cannot infer the types of these attributes without additional help.

The plugin inspects the ``fields`` dict of each versioned object class and
inserts typed attribute definitions into the class, allowing mypy to type-check
code that accesses these attributes.
