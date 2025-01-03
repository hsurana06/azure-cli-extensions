# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# pylint: disable=line-too-long, broad-except, logging-format-interpolation, too-many-public-methods, too-many-boolean-expressions

from copy import deepcopy
from knack.log import get_logger
from azure.mgmt.core.tools import resource_id
from typing import Any, Dict

from azure.cli.core.commands import AzCliCommand
from azure.cli.core.azclierror import ValidationError, CLIInternalError
from azure.cli.command_modules.containerapp.base_resource import BaseResource
from azure.cli.command_modules.containerapp._decorator_utils import load_yaml_file
from azure.cli.core.commands.client_factory import get_subscription_id

from ._constants import CONTAINER_APPS_RP, MANAGED_ENVIRONMENT_RESOURCE_TYPE
from ._utils import parse_service_bindings
from ._models import JavaComponent as JavaComponentModel
from ._client_factory import handle_raw_exception

logger = get_logger(__name__)


class JavaComponentDecorator(BaseResource):
    def __init__(self, cmd: AzCliCommand, client: Any, raw_parameters: Dict, models: str):
        super().__init__(cmd, client, raw_parameters, models)
        self.java_component_def = deepcopy(JavaComponentModel)

    def get_argument_configuration(self):
        return self.get_param("configuration")

    def get_argument_environment_name(self):
        return self.get_param("environment_name")

    def get_environment_id(self, cmd: AzCliCommand):
        return resource_id(
            subscription=get_subscription_id(cmd.cli_ctx),
            resource_group=self.get_argument_resource_group_name(),
            namespace=CONTAINER_APPS_RP,
            type=MANAGED_ENVIRONMENT_RESOURCE_TYPE,
            name=self.get_argument_environment_name()
        )

    def get_argument_java_component_name(self):
        return self.get_param("java_component_name")

    def get_argument_target_java_component_type(self):
        return self.get_param("target_java_component_type")

    def get_argument_service_bindings(self):
        return self.get_param("service_bindings")

    def get_argument_unbind_service_bindings(self):
        return self.get_param("unbind_service_bindings")

    def get_argument_min_replicas(self):
        return self.get_param("min_replicas")

    def get_argument_max_replicas(self):
        return self.get_param("max_replicas")

    def get_argument_route_yaml(self):
        return self.get_param("route_yaml")

    def construct_payload(self):
        self.java_component_def["properties"]["componentType"] = self.get_argument_target_java_component_type()
        self.set_up_service_bindings()
        self.set_up_unbind_service_bindings()
        self.set_up_gateway_route()
        if self.get_argument_min_replicas() is not None and self.get_argument_max_replicas() is not None:
            self.java_component_def["properties"]["scale"] = {
                "minReplicas": self.get_argument_min_replicas(),
                "maxReplicas": self.get_argument_max_replicas()
            }

        if self.get_argument_configuration() is not None:
            configuration_list = []
            for pair in self.get_argument_configuration():
                key_val = pair.split('=', 1)
                if len(key_val) != 2:
                    raise ValidationError("Java configuration must be in format \"<propertyName>=<value> <propertyName>=<value> ...\".")
                configuration_list.append({
                    "propertyName": key_val[0],
                    "value": key_val[1]
                })
            self.java_component_def["properties"]["configurations"] = configuration_list

    def create(self):
        try:
            return self.client.create(
                cmd=self.cmd, resource_group_name=self.get_argument_resource_group_name(),
                environment_name=self.get_argument_environment_name(), name=self.get_argument_java_component_name(),
                java_component_envelope=self.java_component_def,
                no_wait=self.get_argument_no_wait())
        except Exception as e:
            stringErr = str(e)
            if "JavaComponentsNotAllowedForSubscription" in stringErr:
                raise CLIInternalError("Java Components operations are not allowed for the subscription, please use 'az feature register --namespace  Microsoft.App --name JavaComponentsPreview' to register this feature.")

            handle_raw_exception(e)

    def update(self):
        try:
            return self.client.update(
                cmd=self.cmd, resource_group_name=self.get_argument_resource_group_name(),
                environment_name=self.get_argument_environment_name(), name=self.get_argument_java_component_name(),
                java_component_envelope=self.java_component_def,
                no_wait=self.get_argument_no_wait())
        except Exception as e:
            handle_raw_exception(e)

    def show(self):
        try:
            return self.client.show(
                cmd=self.cmd, resource_group_name=self.get_argument_resource_group_name(),
                environment_name=self.get_argument_environment_name(), name=self.get_argument_java_component_name())
        except Exception as e:
            handle_raw_exception(e)

    def list(self):
        try:
            return self.client.list(
                cmd=self.cmd, resource_group_name=self.get_argument_resource_group_name(),
                environment_name=self.get_argument_environment_name())
        except Exception as e:
            handle_raw_exception(e)

    def delete(self):
        try:
            return self.client.delete(
                cmd=self.cmd, resource_group_name=self.get_argument_resource_group_name(),
                environment_name=self.get_argument_environment_name(), name=self.get_argument_java_component_name(),
                no_wait=self.get_argument_no_wait())
        except Exception as e:
            handle_raw_exception(e)

    def set_up_service_bindings(self):
        if self.get_argument_service_bindings() is not None:
            _, service_bindings_def_list = parse_service_bindings(self.cmd,
                                                                  self.get_argument_service_bindings(),
                                                                  self.get_argument_resource_group_name(),
                                                                  self.get_argument_java_component_name(),
                                                                  self.get_environment_id(self.cmd))
            service_bindings_used_map = {update_item["name"]: False for update_item in service_bindings_def_list}

            if self.java_component_def["properties"]["serviceBinds"] is None:
                self.java_component_def["properties"]["serviceBinds"] = []

            for update_item in service_bindings_def_list:
                if service_bindings_used_map[update_item["name"]] is False:
                    self.java_component_def["properties"]["serviceBinds"].append(update_item)

    def set_up_unbind_service_bindings(self):
        if self.get_argument_unbind_service_bindings() is not None:
            new_template = self.java_component_def.setdefault("properties", {})
            existing_template = self.java_component_def["properties"]

            if not self.get_argument_service_bindings():
                new_template["serviceBinds"] = existing_template.get("serviceBinds", [])

            service_bindings_dict = {}
            if new_template["serviceBinds"]:
                service_bindings_dict = {service_binding["name"]: index for index, service_binding in
                                         enumerate(new_template.get("serviceBinds", []))}

            for item in self.get_argument_unbind_service_bindings():
                if item in service_bindings_dict:
                    new_template["serviceBinds"] = [binding for binding in new_template["serviceBinds"] if
                                                    binding["name"] != item]

    def set_up_gateway_route(self):
        if self.get_argument_route_yaml() is not None:
            self.java_component_def["properties"]["springCloudGatewayRoutes"] = self.process_loaded_scg_route()

    def process_loaded_scg_route(self):
        yaml_scg_routes = load_yaml_file(self.get_argument_route_yaml())

        # Check if the loaded YAML is a dictionary
        if not isinstance(yaml_scg_routes, dict):
            raise ValidationError('Invalid YAML provided. Please see https://aka.ms/gateway-for-spring-routes-yaml for a valid Gateway for Spring routes YAML spec.')

        # Ensure that 'springCloudGatewayRoutes' is present and is a list (can be empty)
        routes = yaml_scg_routes.get('springCloudGatewayRoutes')
        if routes is None:
            return []

        if not isinstance(routes, list):
            raise ValidationError('The "springCloudGatewayRoutes" field must be a list. Please see https://aka.ms/gateway-for-spring-routes-yaml for a valid Gateway for Spring routes YAML spec.')

        # Loop through each route and validate the required fields
        for route in routes:
            if not isinstance(route, dict):
                raise ValidationError('Each route must be a dictionary. Please see https://aka.ms/gateway-for-spring-routes-yaml for a valid Gateway for Spring routes YAML spec.')

            # Ensure each route has 'id' and 'uri' fields
            if 'id' not in route or not route['id']:
                raise ValidationError(f'Route is missing required "id" field: {route} Please see https://aka.ms/gateway-for-spring-routes-yaml for a valid Gateway for Spring routes YAML spec.')

            if 'uri' not in route or not route['uri']:
                raise ValidationError(f'Route is missing required "uri" field: {route} Please see https://aka.ms/gateway-for-spring-routes-yaml for a valid Gateway for Spring routes YAML spec.')

            # Ensure predicates and filters are lists; set to empty lists if not provided
            if 'predicates' not in route:
                route['predicates'] = []
            elif not isinstance(route['predicates'], list):
                raise ValidationError(f'The "predicates" field must be a list in route {route["id"]}. Please see https://aka.ms/gateway-for-spring-routes-yaml for a valid Gateway for Spring routes YAML spec.')

            if 'filters' not in route:
                route['filters'] = []
            elif not isinstance(route['filters'], list):
                raise ValidationError(f'The "filters" field must be a list in route {route["id"]}. Please see https://aka.ms/gateway-for-spring-routes-yaml for a valid Gateway for Spring routes YAML spec.')

        return yaml_scg_routes.get('springCloudGatewayRoutes')
