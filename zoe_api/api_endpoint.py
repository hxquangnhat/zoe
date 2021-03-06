# Copyright (c) 2016, Daniele Venzano
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""The real API, exposed as web pages or REST API."""

import logging
import re

import zoe_api.exceptions
import zoe_api.master_api
import zoe_lib.applications
import zoe_lib.exceptions
import zoe_lib.state
from zoe_lib.config import get_conf

log = logging.getLogger(__name__)


class APIEndpoint:
    """
    The APIEndpoint class.

    :type master: zoe_api.master_api.APIManager
    :type sql: zoe_lib.sql_manager.SQLManager
    """
    def __init__(self):
        self.master = zoe_api.master_api.APIManager()
        self.sql = zoe_lib.state.SQLManager(get_conf())

    def execution_by_id(self, uid, role, execution_id) -> zoe_lib.state.sql_manager.Execution:
        """Lookup an execution by its ID."""
        e = self.sql.execution_list(id=execution_id, only_one=True)
        if e is None:
            raise zoe_api.exceptions.ZoeNotFoundException('No such execution')
        assert isinstance(e, zoe_lib.state.sql_manager.Execution)
        if e.user_id != uid and role != 'admin':
            raise zoe_api.exceptions.ZoeAuthException()
        return e

    def execution_list(self, uid, role, **filters):
        """Generate a optionally filtered list of executions."""
        execs = self.sql.execution_list(**filters)
        ret = [e for e in execs if e.user_id == uid or role == 'admin']
        return ret

    def zapp_validate(self, application_description):
        """Validates the passed ZApp description against the supported schema."""
        try:
            zoe_lib.applications.app_validate(application_description)
        except zoe_lib.exceptions.InvalidApplicationDescription as e:
            raise zoe_api.exceptions.ZoeException('Invalid application description: ' + e.message)

    def execution_start(self, uid, role, exec_name, application_description): # pylint: disable=unused-argument
        """Start an execution."""
        try:
            zoe_lib.applications.app_validate(application_description)
        except zoe_lib.exceptions.InvalidApplicationDescription as e:
            raise zoe_api.exceptions.ZoeException('Invalid application description: ' + e.message)

        if 3 > len(exec_name) > 128:
            raise zoe_api.exceptions.ZoeException("Execution name must be between 4 and 128 characters long")
        if not re.match(r'^[a-zA-Z0-9\-]+$', exec_name):
            raise zoe_api.exceptions.ZoeException("Execution name can contain only letters, numbers and dashes. '{}' is not valid.".format(exec_name))

        new_id = self.sql.execution_new(exec_name, uid, application_description)
        success, message = self.master.execution_start(new_id)
        if not success:
            raise zoe_api.exceptions.ZoeException('The Zoe master is unavailable, execution will be submitted automatically when the master is back up ({}).'.format(message))

        return new_id

    def execution_terminate(self, uid, role, exec_id):
        """Terminate an execution."""
        e = self.sql.execution_list(id=exec_id, only_one=True)
        assert isinstance(e, zoe_lib.state.sql_manager.Execution)
        if e is None:
            raise zoe_api.exceptions.ZoeNotFoundException('No such execution')

        if e.user_id != uid and role != 'admin':
            raise zoe_api.exceptions.ZoeAuthException()

        if e.is_active:
            return self.master.execution_terminate(exec_id)
        else:
            raise zoe_api.exceptions.ZoeException('Execution is not running')

    def execution_delete(self, uid, role, exec_id):
        """Delete an execution."""
        e = self.sql.execution_list(id=exec_id, only_one=True)
        assert isinstance(e, zoe_lib.state.sql_manager.Execution)
        if e is None:
            raise zoe_api.exceptions.ZoeNotFoundException('No such execution')

        if e.user_id != uid and role != 'admin':
            raise zoe_api.exceptions.ZoeAuthException()

        if e.is_active:
            raise zoe_api.exceptions.ZoeException('Cannot delete an active execution')

        status, message = self.master.execution_delete(exec_id)
        if status:
            self.sql.execution_delete(exec_id)
            return True, ''
        else:
            raise zoe_api.exceptions.ZoeException(message)

    def service_by_id(self, uid, role, service_id) -> zoe_lib.state.sql_manager.Service:
        """Lookup a service by its ID."""
        service = self.sql.service_list(id=service_id, only_one=True)
        if service is None:
            raise zoe_api.exceptions.ZoeNotFoundException('No such execution')
        if service.user_id != uid and role != 'admin':
            raise zoe_api.exceptions.ZoeAuthException()
        return service

    def service_list(self, uid, role, **filters):
        """Generate a optionally filtered list of services."""
        services = self.sql.service_list(**filters)
        ret = [s for s in services if s.user_id == uid or role == 'admin']
        return ret

    def statistics_scheduler(self, uid_, role_):
        """Retrieve statistics about the scheduler."""
        success, message = self.master.scheduler_statistics()
        if success:
            return message

    def retry_submit_error_executions(self):
        """Resubmit any execution forgotten by the master."""
        waiting_execs = self.sql.execution_list(status=zoe_lib.state.sql_manager.Execution.SUBMIT_STATUS)
        if waiting_execs is None or len(waiting_execs) == 0:
            return
        e = waiting_execs[0]
        success, message = self.master.execution_start(e.id)
        if not success:
            log.warning('Zoe Master unavailable ({}), execution {} still waiting'.format(message, e.id))

    def cleanup_dead_executions(self):
        """Terminates all executions with dead "monitor" services."""
        log.debug('Starting dead execution cleanup task')
        all_execs = self.sql.execution_list()
        for execution in all_execs:
            if execution.is_running:
                for service in execution.services:
                    if service.description['monitor'] and service.is_dead():
                        log.info("Service {} ({}) of execution {} died, terminating execution".format(service.id, service.name, execution.id))
                        self.master.execution_terminate(execution.id)
                        break
        log.debug('Cleanup task finished')

    def execution_endpoints(self, uid: str, role: str, execution: zoe_lib.state.Execution):
        """Return a list of the services and public endpoints available for a certain execution."""
        services_info = []
        endpoints = []
        for service in execution.services:
            services_info.append(self.service_by_id(uid, role, service.id))
            for port in service.description['ports']:
                port_key = str(port['port_number']) + "/" + port['protocol']
                backend_port = self.sql.port_list(only_one=True, service_id=service.id, internal_name=port_key)
                if backend_port.external_ip is not None:
                    endpoint = port['url_template'].format(**{"ip_port": backend_port.external_ip + ":" + str(backend_port.external_port)})
                    endpoints.append((port['name'], endpoint))

        return services_info, endpoints
