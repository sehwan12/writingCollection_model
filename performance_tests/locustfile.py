import base64
from locust import HttpUser, task, between

# 1x1 Pixel Red Dot PNG Base64
DUMMY_IMAGE_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

class HandwritingUser(HttpUser):
    wait_time = between(1, 3)  # Users wait 1-3 seconds between tasks

    def on_start(self):
        """
        Locust 사용자가 시작될 때 호출됩니다.
        여기서 SSL 인증서 확인을 비활성화합니다.
        """
        self.client.verify = False # 모든 요청에 대해 SSL 인증서 확인 비활성화

    @task(5)
    def get_user_profile(self):
        """Test getting user profile (Light DB read)."""
        self.client.get("/api/user/getProfile/1", name="/api/user/getProfile/{id}")

    @task(2)
    def get_user_stats(self):
        """Test getting user statistics (Medium DB read)."""
        self.client.get("/api/user/stats/1", name="/api/user/stats/{id}")

    @task(2)
    def get_step_list(self):
        """Test getting step list (Static Data DB read)."""
        self.client.get("/api/data/step", name="/api/data/step")

    @task(1)
    def generate_text(self):
        """Test the text generation endpoint (Gemini API wrapper)."""
        payload = {
            "form": "WORD",
            "length": 3,
            "con": "받침이 없는 단어"
        }
        self.client.post("/api/text/generate", json=payload, name="/api/text/generate")

    @task(3)
    def evaluate_handwriting(self):
        """Test the handwriting evaluation endpoint (Heavy Compute)."""
        # Note: Ensure user_id=1 exists in your local DB or update this value.
        payload = {
            "user_id": 1,
            "step_id": 1,
            "practice_text": "가",
            "cell_images": {
                "0": [DUMMY_IMAGE_B64]
            },
            "detailed_strokecounts": {
                "0": [3]
            },
            "firstandlast_stroke": {
                "0": [{ "x": 10.5, "y": 20.0 }, 
                      { "x": 30.0, "y": 30.0 },
                      {"x": 30.0, "y": 30.0},
                      {"x": 40.0, "y": 40.0},
                      {"x": 40.0, "y": 40.0},
                      {"x": 50.0, "y": 50.0}
                ]
            },
            "user_type": "CHILD"
        }
        
        self.client.post("/api/step/evaluate", json=payload, name="/api/step/evaluate")

