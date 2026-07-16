"""Contoh client minimal untuk integrasi BatikCraft Studio."""
from pathlib import Path
import requests


class BatikCraftWebClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Token {token}"

    @classmethod
    def login(cls, base_url: str, username: str, password: str):
        response = requests.post(
            f"{base_url.rstrip('/')}/api/v1/auth/token/",
            json={"username": username, "password": password},
            timeout=30,
        )
        response.raise_for_status()
        return cls(base_url, response.json()["token"])

    def upload_nft(self, image_path: Path, *, title: str, project_id: str, metadata: dict, starting_price: str):
        with image_path.open("rb") as image_file:
            response = self.session.post(
                f"{self.base_url}/api/v1/nfts/",
                data={
                    "title": title,
                    "source_project_id": project_id,
                    "source_app_version": "0.4.0",
                    "starting_price": starting_price,
                    "metadata": __import__("json").dumps(metadata),
                },
                files={"image": (image_path.name, image_file, "image/png")},
                timeout=120,
            )
        response.raise_for_status()
        return response.json()

    def publish(self, nft_id: int):
        response = self.session.post(f"{self.base_url}/api/v1/nfts/{nft_id}/publish/", timeout=30)
        response.raise_for_status()
        return response.json()
