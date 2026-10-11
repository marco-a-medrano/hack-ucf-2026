from django.http import JsonResponse
from django.utils import timezone

from ultralytics import YOLO

print("YOLO status good")


def ping(request):
    return JsonResponse({
        "status": "ok",
        "message": "API is running",
        "timestamp": timezone.now().isoformat(),
    })

def queryYOLO(request):

    

    placeholder = 0

    return JsonResponse({
        "key": testNumber,
    })