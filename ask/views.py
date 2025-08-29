import json
import os
from django.shortcuts import render
from django.http import JsonResponse
from django.conf import settings
from .services import IntentParser, exact_toolbox


def test_intent(request):
    """
    Home view that handles intent parsing and execution.
    When user submits a message, it parses the intent and executes it via API.
    """
    context = {}
    
    if request.method == 'POST':
        message = request.POST.get('message', '').strip()
        
        if message:
            try:
                # Initialize intent parser
                session_key = request.session.session_key
                if not session_key:
                    context['chat_result'] = {
                        'message': message,
                        'error': 'No active session found'
                    }
                    return render(request, 'ask/home.html', context)
                
                parser = IntentParser()
                
                # Parse the user's intent
                intent = parser.parse_intent(message)
                
                # Execute the intent via the toolbox
                api_result = exact_toolbox.execute(intent, session_key)
                
                # Prepare the result for display
                chat_result = {
                    'message': message,
                    'intent': intent.to_dict(),
                    'api_result': api_result
                }
                
                # Format API result as JSON for display
                if api_result.get('success') and api_result.get('data'):
                    chat_result['api_result_json'] = json.dumps(api_result['data'], indent=2)
                elif api_result.get('error'):
                    chat_result['error'] = api_result['error']
                
                context['chat_result'] = chat_result
                
            except Exception as e:
                context['chat_result'] = {
                    'message': message,
                    'error': f'An error occurred: {str(e)}'
                }
    
    return render(request, 'ask/home.html', context)


def ai_chat(request):
    """Placeholder for future AI chat functionality"""
    return JsonResponse({'message': 'AI chat not implemented yet'})


def api_forwarder(request, path):
    """Placeholder for API forwarding functionality"""
    return JsonResponse({'message': 'API forwarder not implemented yet'})