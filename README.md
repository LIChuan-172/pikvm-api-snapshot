## Basic Usage

```bash
curl -k -u admin:admin https://<pikvm-ip>/api/streamer/snapshot -o snapshot.jpg
```

This will save the snapshot to the current directory as `snapshot.jpg`.

- The `-k` flag is used to ignore SSL certificate errors.
- The `-u` flag is used to specify the username and password.
- The `-o` flag is used to specify the output file.
- `<pikvm-ip>` is the IP address of the PiKVM device.

## Problem

The command above will not return a jpg image. It will return an json error.
```json
{
    "ok": false,
    "result": {
        "error": "UnavailableError",
        "error_msg": "Service Unavailable"
    }
}
```

## Reason

To use the `streamer` API, you need to enable the streamer service on the PiKVM device.

```bash
curl -k -u admin:admin https://<pikvm-ip>/api/streamer
```

Run this command you will get a json reponse

```json
{
    "ok": true,
    "result": {
        "features": {
            "h264": true,
            "quality": true,
            "resolution": false
        },
        "limits": {
            "desired_fps": {
                "max": 70,
                "min": 0
            },
            "h264_bitrate": {
                "max": 20000,
                "min": 25
            },
            "h264_gop": {
                "max": 60,
                "min": 0
            }
        },
        "params": {
            "desired_fps": 40,
            "h264_bitrate": 25,
            "h264_gop": 0,
            "quality": 80
        },
        "snapshot": {
            "saved": null
        },
        "streamer": null
    }
}
```

If the `streamer` is `null`, you need to enable the streamer service on the PiKVM device.

## Solution

Enable the streamer service on the PiKVM device by running the following command.

```bash
websocat -k wss://<pikvm-ip>/api/ws -H X-KVMD-User:admin -H X-KVMD-Passwd:admin
```

This will open a websocket connection to the PiKVM device.

Then run the following command to check if the streamer service is enabled.

```bash
curl -k -u admin:admin https://<pikvm-ip>/api/streamer
```

The response should be similar to the following.

```json
{
    "ok": true,
    "result": {
        "features": "...",
        "streamer": {
            "encoder": {
                "quality": 80,
                "type": "M2M-IMAGE"
            },
            "h264": {
                "bitrate": 25,
                "fps": 0,
                "gop": 0,
                "online": false
            },
            "instance_id": "",
            "sinks": {
                "h264": {
                    "has_clients": false
                },
                "jpeg": {
                    "has_clients": false
                }
            },
            "source": {
                "captured_fps": 50,
                "desired_fps": 40,
                "online": true,
                "resolution": {
                    "height": 1080,
                    "width": 1920
                }
            },
            "stream": {
                "clients": 0,
                "clients_stat": {},
                "queued_fps": 0
            }
        }
    }
}
```

If the `streamer` is not `null`, you can use the `api/streamer/snapshot` API to get the snapshot.
