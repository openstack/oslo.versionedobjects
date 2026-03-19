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

A minimal ``objects/base.py`` looks like this:

.. code:: python

   from oslo_versionedobjects import base as ovo_base
   from oslo_versionedobjects import fields as ovo_fields


   class MyProjectObjectRegistry(ovo_base.VersionedObjectRegistry):
       def registration_hook(self, cls, index):
           # Make registered objects accessible as myproject.objects.Foo
           from myproject import objects
           setattr(objects, cls.obj_name(), cls)


   class MyProjectObject(ovo_base.VersionedObject):
       OBJ_PROJECT_NAMESPACE = 'myproject'


   class MyProjectPersistentObject:
       """Mixin for objects that are stored in the database."""
       fields = {
           'created_at': ovo_fields.DateTimeField(nullable=True),
           'updated_at': ovo_fields.DateTimeField(nullable=True),
           'deleted_at': ovo_fields.DateTimeField(nullable=True),
           'deleted': ovo_fields.BooleanField(default=False),
       }

Once you have your base class defined, you can define your actual object
classes. Objects classes should be created for all resources/objects passed via
RPC as IDs or dicts in order to:

* spare the database (or other resource) from extra calls
* pass objects instead of dicts, which are tagged with their version
* handle all object versions in one place (the ``obj_make_compatible`` method)

To make sure all objects are accessible at all times, you should import them in
``__init__.py`` in the ``objects/`` directory and expose them via a
``register_all()`` function. This function is called at service startup to
ensure objects are registered before any RPC communication takes place.

A typical ``objects/__init__.py`` looks like this:

.. code:: python

   # NOTE: When objects are registered, an attribute is set on this module
   # automatically, pointing to the newest/latest version of the object.
   # This allows callers to use myproject.objects.Foo without importing
   # the specific module.


   def register_all():
       # NOTE: You must make sure your object gets imported in this function
       # in order for it to be registered by services that may need to receive
       # it via RPC.
       __import__('myproject.objects.thing')

Finally, you should create an object registry by subclassing
:class:`oslo_versionedobjects.base.VersionedObjectRegistry`. The object
registry is the place where all objects are registered. All object classes
should be registered by the
:attr:`oslo_versionedobjects.base.ObjectRegistry.register` class decorator.

Defining objects
----------------

Each object class represents a versioned resource type. At minimum, an object
must declare its ``VERSION``, a ``fields`` dictionary, and be decorated with
the registry's ``@register`` decorator.

A concrete object with database interaction looks like this:

.. code:: python

   from oslo_versionedobjects import base as ovo_base

   from myproject.db import api as dbapi
   from myproject.objects import base
   from myproject.objects import fields as object_fields


   @base.MyProjectObjectRegistry.register
   class Thing(base.MyProjectObject, base.MyProjectPersistentObject,
               ovo_base.VersionedObjectDictCompat):
       # Version 1.0: Initial version
       # Version 1.1: Added 'description' field
       VERSION = '1.1'

       fields = {
           'id': object_fields.IntegerField(),
           'uuid': object_fields.UUIDField(nullable=True),
           'name': object_fields.StringField(nullable=True),
           'description': object_fields.StringField(nullable=True),
           'extra': object_fields.FlexibleDictField(nullable=True),
       }

       @classmethod
       @ovo_base.remotable
       def get_by_uuid(cls, context, uuid):
           db_thing = dbapi.get_thing_by_uuid(uuid)
           return cls._from_db_object(context, cls(), db_thing)

       @classmethod
       @ovo_base.remotable
       def list(cls, context, limit=None, marker=None):
           db_things = dbapi.get_thing_list(limit=limit, marker=marker)
           return cls._from_db_object_list(context, db_things)

       @ovo_base.remotable
       def create(self, context=None):
           values = self.obj_get_changes()
           db_thing = dbapi.create_thing(values)
           self._from_db_object(self._context, self, db_thing)

       @ovo_base.remotable
       def save(self, context=None):
           updates = self.obj_get_changes()
           db_thing = dbapi.update_thing(self.uuid, updates)
           self._from_db_object(self._context, self, db_thing)

       @ovo_base.remotable
       def destroy(self, context=None):
           dbapi.destroy_thing(self.uuid)
           self.obj_reset_changes()

       def obj_make_compatible(self, primitive, target_version):
           super().obj_make_compatible(primitive, target_version)
           target_version = versionutils.convert_version_to_tuple(target_version)
           if target_version < (1, 1) and 'description' in primitive:
               del primitive['description']

The ``_from_db_object`` static method is responsible for mapping a database row
to the object's fields and resetting the change-tracking state:

.. code:: python

   @staticmethod
   def _from_db_object(context, obj, db_object, fields=None):
       fields = fields or obj.fields
       for field in fields:
           setattr(obj, field, db_object[field])
       obj._context = context
       obj.obj_reset_changes()
       return obj

The ``obj_make_compatible`` method is the key mechanism for rolling upgrades:
it is called when an object needs to be sent to a service running an older
version of the code. It must strip or transform any fields that did not exist
in the target version.

List objects
~~~~~~~~~~~~

Resources that can be retrieved as a collection should have a corresponding
list object. A list object uses
:class:`oslo_versionedobjects.base.ObjectListBase` and its ``fields``
dictionary contains a single entry, ``objects``, which is a
:class:`oslo_versionedobjects.fields.ListOfObjectsField`:

.. code:: python

   @base.MyProjectObjectRegistry.register
   class ThingList(base.ObjectListBase, base.MyProjectObject):
       # Version 1.0: Initial version
       #              Thing <= version 1.1
       VERSION = '1.0'

       fields = {
           'objects': object_fields.ListOfObjectsField('Thing'),
       }

       @classmethod
       @ovo_base.remotable
       def get_all(cls, context):
           db_things = dbapi.get_thing_list()
           return ovo_base.obj_make_list(context, cls(context),
                                         Thing, db_things)

The list object's version should be bumped whenever the version of the
contained object type is bumped.

Using custom field types
------------------------

New field types can be implemented by inheriting from
:class:`oslo_versionedobjects.field.Field` and overwriting the `from_primitive`
and `to_primitive` methods.

By subclassing :class:`oslo_versionedobjects.fields.AutoTypedField` you can
stack multiple fields together, making sure even nested data structures are
being validated.

A common pattern is a ``FlexibleDictField`` that accepts both strings and dicts
(useful for data stored as JSON blobs in the database):

.. code:: python

   import ast
   from oslo_versionedobjects import fields as ovo_fields


   class FlexibleDict(ovo_fields.FieldType):
       def coerce(self, obj, attr, value):
           if isinstance(value, str):
               value = ast.literal_eval(value)
           return dict(value)


   class FlexibleDictField(ovo_fields.AutoTypedField):
       AUTO_TYPE = FlexibleDict()

For enumerated types, inherit from :class:`oslo_versionedobjects.fields.Enum`
and then wrap it in a :class:`oslo_versionedobjects.fields.BaseEnumField`:

.. code:: python

   from oslo_versionedobjects import fields as ovo_fields


   class ThingState(ovo_fields.Enum):
       ACTIVE = 'active'
       PENDING = 'pending'
       ERROR = 'error'

       ALL = (ACTIVE, PENDING, ERROR)

       def __init__(self):
           super().__init__(valid_values=ThingState.ALL)


   class ThingStateField(ovo_fields.BaseEnumField):
       AUTO_TYPE = ThingState()

Custom fields should be defined in a ``fields.py`` module within the
``objects/`` package, and re-exported from there. Projects typically also
re-export the standard oslo.versionedobjects field types from this module to
provide a single import point for all field types:

.. code:: python

   # objects/fields.py
   from oslo_versionedobjects import fields as ovo_fields

   # Re-export standard field types
   IntegerField = ovo_fields.IntegerField
   UUIDField = ovo_fields.UUIDField
   StringField = ovo_fields.StringField
   BooleanField = ovo_fields.BooleanField
   DateTimeField = ovo_fields.DateTimeField
   ListOfStringsField = ovo_fields.ListOfStringsField
   ObjectField = ovo_fields.ObjectField
   ListOfObjectsField = ovo_fields.ListOfObjectsField

   # Project-specific field types
   class FlexibleDictField(ovo_fields.AutoTypedField):
       ...

Configure serialization
-----------------------

To transfer objects by RPC, subclass the
:class:`oslo_versionedobjects.base.VersionedObjectSerializer` setting the
OBJ_BASE_CLASS property to the previously defined Object class.

.. code:: python

   # objects/base.py (add to existing file)
   from oslo_versionedobjects import base as ovo_base


   class MyProjectObjectSerializer(ovo_base.VersionedObjectSerializer):
       OBJ_BASE_CLASS = MyProjectObject

The serializer is then passed to oslo.messaging when creating RPC servers and
clients. For example, to use a custom serializer with `oslo_messaging`__:

.. code:: python

   # common/rpc_service.py
   import oslo_messaging as messaging
   from myproject.objects import base as objects_base


   class RPCService:
       def start(self):
           serializer = objects_base.MyProjectObjectSerializer()
           target = messaging.Target(topic=self.topic, server=self.host)
           endpoints = [self.manager]
           self.rpcserver = messaging.get_rpc_server(
               transport, target, endpoints, serializer=serializer)
           self.rpcserver.start()

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

A typical implementation delegates to the conductor service's RPC API, so that
object methods decorated with ``@remotable`` are executed on the conductor:

.. code:: python

   # objects/indirection.py
   from oslo_versionedobjects import base as ovo_base

   from myproject.conductor import rpcapi as conductor_api


   class MyProjectObjectIndirectionAPI(ovo_base.VersionedObjectIndirectionAPI):
       def __init__(self):
           super().__init__()
           self._conductor = conductor_api.ConductorAPI()

       def object_action(self, context, objinst, objmethod, args, kwargs):
           return self._conductor.object_action(
               context, objinst, objmethod, args, kwargs)

       def object_class_action_versions(self, context, objname, objmethod,
                                        object_versions, args, kwargs):
           return self._conductor.object_class_action_versions(
               context, objname, objmethod, object_versions, args, kwargs)

       def object_backport_versions(self, context, objinst, object_versions):
           return self._conductor.object_backport_versions(
               context, objinst, object_versions)

The indirection API is then attached to the base object class at service
startup. Services that act as clients (e.g. the API tier) attach the
indirection API so that ``@remotable`` calls are forwarded to the conductor.
Services that act as servers (e.g. the conductor itself) leave it unset or set
it to ``None`` so that ``@remotable`` calls are executed locally:

.. code:: python

   # command/api.py  (API service entry point)
   from myproject.objects import base as objects_base
   from myproject.objects import indirection


   def main():
       # Attach the indirection API so that remotable object methods
       # are executed on the conductor via RPC.
       objects_base.MyProjectObject.indirection_api = (
           indirection.MyProjectObjectIndirectionAPI()
       )
       # ... start the WSGI server


   # command/conductor.py  (conductor service entry point)
   def main():
       # The conductor executes remotable methods locally; no indirection API.
       # objects_base.MyProjectObject.indirection_api = None  (default)
       # ... start the RPC server
