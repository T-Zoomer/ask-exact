from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from exact_oauth.services import get_service
import json


def home(request):
    context = {}
    
    if request.method == 'GET' and any(param in request.GET for param in ['current_year', 'current_period', 'previous_year', 'previous_year_period', 'currency_code']):
        try:
            session_key = request.session.session_key
            if not session_key:
                context['error'] = 'No session available'
            else:
                service = get_service(session_key)
                result = service.get_profit_loss_overview(
                    current_year=int(request.GET.get('current_year')) if request.GET.get('current_year') else None,
                    current_period=int(request.GET.get('current_period')) if request.GET.get('current_period') else None,
                    previous_year=int(request.GET.get('previous_year')) if request.GET.get('previous_year') else None,
                    previous_year_period=int(request.GET.get('previous_year_period')) if request.GET.get('previous_year_period') else None,
                    currency_code=request.GET.get('currency_code')
                )
                
                if result:
                    context['profit_loss_data'] = json.dumps(result, indent=2)
                else:
                    context['error'] = 'Failed to fetch data'
                    
        except ValueError as e:
            context['error'] = str(e)
        except Exception as e:
            context['error'] = 'Internal server error'
    
    return render(request, 'ask/home.html', context)



@require_http_methods(["GET"])
def api_profit_loss_overview(request):
    try:
        session_key = request.session.session_key
        if not session_key:
            return JsonResponse({'error': 'No session available'}, status=401)

        service = get_service(session_key)

        # Forward all GET query params to the API call
        query_params = request.GET.dict()

        result = service.get_profit_loss_overview(**query_params)

        if result:
            return JsonResponse(result, safe=False)
        else:
            return JsonResponse({'error': 'Failed to fetch data'}, status=500)

    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'error': 'Internal server error'}, status=500)
