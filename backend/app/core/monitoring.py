"""Sentry is opt-in. Never send bodies, bearer URLs, locals, breadcrumbs or user data."""


def scrub_event(event, hint=None):
    # Reconstruct an allowlist instead of trying to blacklist every sensitive field.
    result = {
        k: event[k]
        for k in ("event_id", "timestamp", "platform", "level", "release", "environment", "type")
        if k in event
    }
    if "exception" in event:
        values = []
        for exception in event["exception"].get("values", [])[:5]:
            item = {
                "type": exception.get("type", "Error"),
                "value": "An application error occurred.",
            }
            frames = exception.get("stacktrace", {}).get("frames", [])[-50:]
            item["stacktrace"] = {
                "frames": [
                    {
                        k: f[k]
                        for k in ("filename", "function", "module", "lineno", "in_app")
                        if k in f
                    }
                    for f in frames
                ]
            }
            values.append(item)
        result["exception"] = {"values": values}
    return result


def initialize_monitoring(settings):
    if settings.sentry_dsn is None:
        return None
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        environment=settings.app_env,
        release=settings.app_version,
        default_integrations=False,
        auto_enabling_integrations=False,
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        before_send=scrub_event,
        before_send_transaction=scrub_event,
        before_breadcrumb=lambda *_: None,
        traces_sample_rate=0,
    )
    return sentry_sdk.get_client()


def report_exception(error, settings):
    if settings.sentry_dsn is not None:
        import sentry_sdk

        sentry_sdk.capture_exception(error)
