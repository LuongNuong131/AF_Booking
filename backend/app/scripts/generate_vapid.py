"""Write a raw VAPID private key to a new 0600 file; print only its public key."""

import argparse
import base64
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-file", required=True)
    args = parser.parse_args()
    key = ec.generate_private_key(ec.SECP256R1())

    def encode(value):
        return base64.urlsafe_b64encode(value).decode().rstrip("=")

    private = encode(key.private_numbers().private_value.to_bytes(32, "big"))
    public = encode(
        key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    )
    descriptor = os.open(args.private_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(private + "\n")
    print("VAPID_PUBLIC_KEY=" + public)
    print("Private key saved to the requested file. Enter it securely in server settings.")


if __name__ == "__main__":
    main()
