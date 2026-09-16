"""Normalize CloudTrail management creation calls across AWS services."""

import re

ROUTINE_ACTIONS = {
    "CreateLogStream",
    "CreateNetworkInterface",
    "DeleteNetworkInterface",
    "RegisterTargets",
    "DeregisterTargets",
}

PROVISION_ACTIONS = {
    "RunInstances",
    "RunTask",
    "RunJobFlow",
    "AllocateAddress",
    "AllocateHosts",
    "RequestSpotInstances",
    "RequestSpotFleet",
    "RestoreDBInstanceFromDBSnapshot",
    "RestoreDBClusterFromSnapshot",
    "RestoreDBInstanceToPointInTime",
    "RestoreDBClusterToPointInTime",
    "RestoreTableFromBackup",
    "RestoreTableToPointInTime",
}


def generic_ids(request, response):
    keys = {
        "arn",
        "resourcearn",
        "clusterarn",
        "servicearn",
        "tablearn",
        "functionarn",
        "rolearn",
        "stackid",
        "repositoryarn",
        "loadbalancerarn",
        "targetgrouparn",
        "queueurl",
        "allocationid",
        "groupid",
        "jobflowid",
        "taskarn",
        "bucketarn",
        "domainarn",
    }
    values = []

    def visit(node, depth=0):
        if depth > 4 or len(values) >= 20:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if key.lower() in keys and isinstance(value, str):
                    values.append(value)
                elif isinstance(value, (dict, list)):
                    visit(value, depth + 1)
        elif isinstance(node, list):
            for value in node[:20]:
                visit(value, depth + 1)

    visit(response)
    if not values:
        for key in (
            "resourceName",
            "bucketName",
            "clusterName",
            "queueName",
            "serviceName",
            "tableName",
            "repositoryName",
            "domainName",
            "stackName",
            "functionName",
            "roleName",
            "name",
        ):
            if isinstance(request.get(key), str):
                values.append(request[key])
                break
    return list(dict.fromkeys(values))[:20]


def clean(value):
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(value))[:300]


def normalize_event(envelope, account, include_changes=False):
    if envelope.get("detail-type") != "AWS API Call via CloudTrail":
        return None
    detail = envelope.get("detail", {})
    action = detail.get("eventName", "")
    source = detail.get("eventSource", "")
    if not isinstance(action, str):
        return None
    creation = action.startswith("Create") or action in PROVISION_ACTIONS
    mutation = action.startswith(
        (
            "Update",
            "Modify",
            "Delete",
            "Attach",
            "Detach",
            "Start",
            "Stop",
            "Terminate",
            "Associate",
            "Disassociate",
            "Register",
            "Deregister",
            "Put",
            "Release",
        )
    )
    if action in {"CreateToken", "CreateAccessKey", "CreateSession"}:
        return None
    if not (creation or (include_changes and mutation)):
        return None
    if not re.fullmatch(r"[a-z0-9.-]+\.amazonaws\.com(?:\.cn)?", source):
        return None
    if detail.get("readOnly") in (True, "true") or detail.get("managementEvent") is False:
        return None
    if detail.get("eventCategory", "Management") != "Management":
        return None
    if detail.get("errorCode") or detail.get("errorMessage"):
        return None
    if envelope.get("account") != account or detail.get("recipientAccountId", account) != account:
        raise ValueError("Event account does not match configured account")
    event_id = detail.get("eventID") or envelope.get("id")
    event_time = detail.get("eventTime") or envelope.get("time")
    if not event_id or not event_time:
        raise ValueError("Event is missing an ID or timestamp")
    action = detail["eventName"]
    request = detail.get("requestParameters") or {}
    response = detail.get("responseElements") or {}
    if (
        response.get("errorCode")
        or response.get("errorMessage")
        or (response.get("failures") and not response.get("tasks"))
    ):
        return None
    resource_ids = []
    if action == "RunInstances":
        resource_ids = [
            i["instanceId"] for i in response.get("instancesSet", {}).get("items", []) if i.get("instanceId")
        ]
    elif action == "CreateNatGateway":
        resource_ids = [response.get("natGateway", {}).get("natGatewayId")]
    elif action == "CreateVolume":
        resource_ids = [response.get("volumeId")]
    elif action in {"AttachVolume", "DetachVolume", "DeleteVolume"}:
        resource_ids = [request.get("volumeId")]
    elif action in {"CreateDBInstance", "CreateDBCluster"}:
        resource_ids = [
            request.get("dBInstanceIdentifier")
            or request.get("dbInstanceIdentifier")
            or request.get("dBClusterIdentifier")
            or request.get("dbClusterIdentifier")
        ]
    elif source == "lambda.amazonaws.com" and action.startswith("CreateFunction"):
        resource_ids = [response.get("functionArn") or request.get("functionName")]
    else:
        resource_ids = generic_ids(request, response)
    resource_ids = [clean(r) for r in resource_ids if r]
    if not resource_ids:
        resource_ids = [clean(r) for r in generic_ids(request, response)]
    identity = detail.get("userIdentity") or {}
    # Preserve the actual AWS principal. Do not invent a human behind a deployment role.
    actor = identity.get("arn") or identity.get("principalId") or identity.get("invokedBy") or "Unknown"
    return {
        "id": f"event:{account}:{clean(event_id)}",
        "time": clean(event_time),
        "account_id": account,
        "region": clean(envelope.get("region", "unknown")),
        "action": action,
        "change_kind": "creation" if creation else "change",
        "service": source.removesuffix(".cn").removesuffix(".amazonaws.com"),
        "resource_ids": resource_ids or ["ID unavailable"],
        "actor": clean(actor),
        "owner": "Unassigned",
        "estimate": None,
        "status": "Creation API accepted; final provisioning status is not verified"
        if creation
        else "Change API accepted; final resource state is not verified",
    }


def render_event(event):
    lines = [
        "AWS resource creation detected",
        f"Account: {event['account_id']}",
        f"Action: {event['action']}",
        f"Service: {event.get('service', 'AWS')}",
        f"Resources: {', '.join(event['resource_ids'])}",
        f"Region: {event['region']}",
        f"Time: {event['time']}",
        f"Actor: {event['actor']}",
        f"Owning team: {event['owner']}",
        f"Status: {event['status']}",
    ]
    estimate = event.get("estimate")
    if estimate:
        lines += [f"Estimated compute cost: USD {estimate['monthly']}/month", estimate["assumptions"]]
    else:
        lines += ["Cost estimate unavailable. Actual costs will arrive in billing data."]
    if event.get("enrichment_warning"):
        lines += [event["enrichment_warning"]]
    lines += [
        "Next step: confirm the owner, environment and expected lifetime.",
        "This notification does not establish that the resource caused a spending increase.",
        f"Evidence: {event['id']}",
    ]
    return "\n".join(lines) + "\n"
