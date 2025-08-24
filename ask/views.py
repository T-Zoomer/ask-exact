from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from exact_oauth.services import get_service
import json


def home(request):
    return render(request, 'ask/home.html')


@require_http_methods(["GET"])
def api_forwarder(request, path):
    try:
        session_key = request.session.session_key
        if not session_key:
            return JsonResponse({'error': 'No session available'}, status=401)

        service = get_service(session_key)

        query_params = request.GET.dict()

        response = service.get(path, params=query_params)

        if response.status_code == 200:
            return JsonResponse(response.json(), safe=False)
        else:
            return JsonResponse(
                {'error': f'Exact API returned status {response.status_code}', 'details': response.text}, 
                status=response.status_code
            )

    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'error': 'Internal server error'}, status=500)
