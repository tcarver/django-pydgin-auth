from django.test import TestCase
from django.db import router
from django.contrib.auth.models import User, Group, Permission
from django.test.client import RequestFactory, Client
import logging
from django.contrib.contenttypes.models import ContentType
from pydgin_auth.admin import ElasticPermissionModelFactory
from pydgin_auth.permissions import check_index_perms
from django.shortcuts import get_object_or_404
logger = logging.getLogger(__name__)


class PydginAuthTestCase(TestCase):

    multi_db = True

    def setUp(self):
        '''Method called to prepare the test , is called immediately before calling the test method.
        Create test_user and add it to READ group'''
        # Every test needs a client.
        self.client = Client()
        # Every test needs access to the request factory.
        self.factory = RequestFactory()
        self.group, created = Group.objects.get_or_create(name='READ')  # @UnusedVariable
        self.user = User.objects.create_user(
            username='test_user', email='test@test.com', password='test_pass')
        self.user.groups.add(self.group)
        ElasticPermissionModelFactory.create_dynamic_models()

    def test_routers(self):
        '''Test if the routers are available to route to different databases'''
        logger.debug('running test_routers')
        self.original_routers = router.routers

        routers = []
        for router_ in self.original_routers:
            routers.append(router_.__class__.__name__)

        self.assertTrue('AuthRouter' in routers, "Found AuthRouter in routers")
        self.assertTrue('DefaultRouter' in routers, "Found DefaultRouter in routers")

    def test_login(self):
        '''Test login. First try to login with invalid credentials, and try again with right credentials again'''
        logger.debug('running test_login')
        response = self.client.get('/accounts/login/', follow=True)
        # check if redirected to login
        self.assertTemplateUsed(response, 'registration/login.html')

        response = self.client.post('/accounts/login/', {'username': 'test_invalid', 'password': 'test_pass'})
        self.assertTrue(response.status_code, "200")
        response_string = response.content.decode('utf-8')
        self.assertTrue("The username and password provided is not valid/recognised" in response_string)

        response = self.client.post('/accounts/login/', {'username': 'test_user', 'password': 'test_pass'})
        self.assertTrue(response.status_code, "200")
        self.assertIn('_auth_user_id', self.client.session)
        self.assertEqual(User.objects.get(id=self.client.session['_auth_user_id']).username, 'test_user')

    def test_register_user(self):
        '''Test registration. First try to login with out agreeing to terms and
        try to register again with is_terms_agreed set'''
        logger.debug('running test_register_user')
        response = self.client.get('/accounts/register/', follow=True)
        # check if redirected to registration page
        self.assertTemplateUsed(response, 'registration/registration_form.html')
        self.client.post('/accounts/register/',
                         {'username': 'new_user', 'email': 'newuser@new.com',
                          'password1': 'newtest', 'password2': 'newtest'})
        self.assertEqual(response.status_code, 200)
        users = User.objects.all()
        user_present = False
        for user in users:
            if user.username == 'new_user':
                user_present = True
                break

        self.assertFalse(user_present, "new_user not in Users before is_terms_agreed")

        self.client.post('/accounts/register/',
                         {'username': 'new_user', 'email': 'newuser@new.com',
                          'password1': 'newtest', 'password2': 'newtest', 'is_terms_agreed': '1'})
        self.assertEqual(response.status_code, 200)
        users = User.objects.all()
        for user in users:
            if user.username == 'new_user':
                user_present = True
                break

        self.assertTrue(user_present, "new_user in Users list after is_terms_agreed")

    def test_create_groups(self):
        '''Test if we get back the READ group without creating it (created is false)
        and other groups should get created (created is True)'''
        read_group, created = Group.objects.get_or_create(name='READ')
        self.assertEqual(read_group.name, "READ")
        self.assertEqual(created, False)

        dil_group, created = Group.objects.get_or_create(name='DIL')
        self.assertEqual(dil_group.name, "DIL")
        self.assertTrue(created)

        curator_group, created = Group.objects.get_or_create(name='CURATOR')
        self.assertEqual(curator_group.name, "CURATOR")
        self.assertTrue(created)

        pydgin_admin_group, created = Group.objects.get_or_create(name='ADMIN')
        self.assertEqual(pydgin_admin_group.name, "ADMIN")
        self.assertTrue(created)

    def test_users_groups_perms(self):
        '''Test to create users, create groups, assign users to group, check permissions'''
        dil_group, created = Group.objects.get_or_create(name='DIL')
        self.assertTrue(created)
        dil_user = User.objects.create_user(
            username='test_dil', email='test_dil@test.com', password='test123')
        dil_user.groups.add(dil_group)
        self.assertTrue(dil_user.groups.filter(name='DIL').exists())

        all_groups_of_dil_user = dil_user.groups.values_list('name', flat=True)
        self.assertTrue("DIL" in all_groups_of_dil_user, "Found DIL in groups")
        self.assertTrue("READ" in all_groups_of_dil_user, "Found READ in groups")

        # create the content type
        test_idx = 'disease'
        test_model = test_idx.lower() + ElasticPermissionModelFactory.PERMISSION_MODEL_SUFFIX
        idx_names = [test_model]

        # create permissions on models and retest again to check if the idx could be seen
        content_type, created = ContentType.objects.get_or_create(
            model=test_model, app_label="elastic",
        )

        # check if you can see the index
        idx_names_after_check, idx_types_after_check = check_index_perms(dil_user, idx_names)  # @UnusedVariable
        self.assertTrue('disease' not in idx_names_after_check, 'Index disease could not be seen')

        # create permission and assign ...Generally we create via admin interface
        can_read_permission, create = Permission.objects.get_or_create(codename='can_read_disease_idx',  # @UnusedVariable
                                                                       name='Can Read disease Idx',
                                                                       content_type=content_type)

        # have created permission but not yet assigned to anyone
        idx_names_after_check, idx_types_after_check = check_index_perms(dil_user, idx_names)  # @UnusedVariable
        self.assertFalse('gene' in idx_names_after_check, 'Index gene could not not be seen')

        # As we have not yet assigned the permission to dil_user the test should return False
        self.assertFalse(dil_user.has_perm('elastic.can_read_disease_idx'),
                         "dil_user has no perm 'elastic.can_read_disease_idx' yet ")

        # Add the permission to dil_group
        dil_group.permissions.add(can_read_permission)
        dil_user = get_object_or_404(User, pk=dil_user.id)
        available_group_perms = dil_user.get_group_permissions()
        self.assertTrue('elastic.can_read_disease_idx' in available_group_perms,
                        "dil_user has perm 'elastic.can_read_disease_idx' yet ")

        idx_names_after_check, idx_types_after_check = check_index_perms(dil_user, idx_names)  # @UnusedVariable

        # As we have assigned the permission to dil_user the test should return True
        self.assertTrue(dil_user.has_perm('elastic.can_read_disease_idx'),
                        "dil_user has perm 'elastic.can_read_disease_idx' ")
        self.assertTrue('disease_idx' in idx_names_after_check, 'Index disease could be seen')
