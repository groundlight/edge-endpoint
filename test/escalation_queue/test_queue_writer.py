from app.core.kubernetes_management import InferenceDeploymentManager
from app.escalation_queue.queue_writer import EscalationInfo, QueueWriter

print(InferenceDeploymentManager)


def test_basic_write():
    data = {"detector_id": "test_id", "image_path": "test_path"}
    escalation_info = EscalationInfo(**data)

    writer = QueueWriter()

    writer.write_escalation(escalation_info)
