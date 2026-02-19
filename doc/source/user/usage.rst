=======
 Usage
=======

Incorporating *oslo.versionedobjects* into your project can be accomplished in
the following steps:

Initial scaffolding
-------------------

By convention, objects reside in the `<project>/objects` directory. This is the
place from which all objects should be imported.

Start the implementation by creating `objects/base.py` with a subclass of the
:class:`oslo_versionedobjects.base.VersionedObject`. This class will form the
base class for all objects in the project. You need to populate the
``OBJ_PROJECT_NAMESPACE`` property.

.. note::

    ``OBJ_SERIAL_NAMESPACE`` is used only for backward compatibility and
    should not be set in new projects.

You may also wish to optionally include the following mixins:

* :class:`oslo_versionedobjects.base.VersionedPersistentObject`

    A mixin class for persistent objects can be created, defining repeated
    fields like ``created_at``, ``updated_at``. Fields are defined in the fields
    property (which is a dict).

* :class:`oslo_versionedobjects.base.VersionedObjectDictCompat`

    If objects were previously passed as dicts (a common situation), this class
    can be used as a mixin class to support dict operations.

Once you have you base class defined, you can define your actual object
classes. Objects classes should be created for all resources/objects passed via
RPC as IDs or dicts in order to:

* spare the database (or other resource) from extra calls
* pass objects instead of dicts, which are tagged with their version
* handle all object versions in one place (the ``obj_make_compatible`` method)

To make sure all objects are accessible at all times, you should import them
in ``__init__.py`` in the ``objects/`` directory and expose them via
``__all__``.

Finally, you should create an object registry by subclassing
:class:`oslo_versionedobjects.base.VersionedObjectRegistry`. The object
registry is the place where all objects are registered. All object classes
should be registered by the
:attr:`oslo_versionedobjects.base.ObjectRegistry.register` class decorator.

Using custom field types
------------------------

New field types can be implemented by inheriting from
:class:`oslo_versionedobjects.field.Field` and overwriting the `from_primitive`
and `to_primitive` methods.

By subclassing :class:`oslo_versionedobjects.fields.AutoTypedField` you can
stack multiple fields together, making sure even nested data structures are
being validated.

Configure serialization
-----------------------

To transfer objects by RPC, subclass the
:class:`oslo_versionedobjects.base.VersionedObjectSerializer` setting the
OBJ_BASE_CLASS property to the previously defined Object class.

For example, to use a custom serializer with `oslo_messaging`__:

.. code:: python

   serializer = RequestContextSerializer(objects_base.MagnumObjectSerializer())
   target = messaging.Target(topic=topic, server=server)
   self._server = messaging.get_rpc_server(transport, target, handlers, serializer=serializer)

.. __: https://docs.openstack.org/oslo.messaging/latest/

Implement the indirection API
-----------------------------

*oslo.versionedobjects* supports "remotable" method calls. These are calls of
the object methods and classmethods which can be executed locally or remotely
depending on the configuration. Setting the ``indirection_api`` as a property
of an object relays the calls to decorated methods through the defined RPC API.
The attachment of the ``indirection_api`` should be handled by configuration at
startup time.

The second function of the indirection API is backporting. When the object
serializer attempts to deserialize an object with a future version not
supported by the current instance, it calls the ``object_backport`` method in
an attempt to backport the object to a version which can then be handled as
normal.

The :class:`oslo_versionedobjects.base.VersionedObjectIndirectionAPI` class
provides a base class for implementing your own indirection API.
