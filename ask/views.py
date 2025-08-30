import json
import os
from django.shortcuts import render
from django.http import JsonResponse
from django.conf import settings
from .code import IntentParser, exact_toolbox


def home(request):
    """
    Home view - displays the chat interface
    """
    return render(request, 'ask/home.html')


def chat_message(request):
    """
    HTMX endpoint that handles chat messages and returns rendered chat message template
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    message = request.POST.get('message', '').strip()
    if not message:
        return JsonResponse({'error': 'Message required'}, status=400)
    
    # Initialize context for template
    context = {
        'user_message': message,
        'error': None,
        'intent': None,
        'api_result': None
    }
    
    try:
        # Get session key for API calls
        session_key = request.session.session_key
        if not session_key:
            context['error'] = 'No active session found. Please refresh the page and try again.'
            return render(request, 'ask/chat_message.html', context)
        
        # Initialize intent parser
        parser = IntentParser()
        
        # Parse the user's intent
        intent = parser.parse_intent(message)
        context['intent'] = intent
        
        # Execute the intent via the toolbox
        api_result = exact_toolbox.execute(intent, session_key)
        context['api_result'] = api_result
        
        # Format raw JSON for display
        if api_result.get('success') and api_result.get('data'):
            context['api_result_json'] = json.dumps(api_result['data'], indent=2)
        
        # Check if there was an error
        if api_result.get('error'):
            context['error'] = api_result['error']
            
    except Exception as e:
        context['error'] = f'An error occurred: {str(e)}'
    
    return render(request, 'ask/chat_message.html', context)


def ai_chat(request):
    """Placeholder for future AI chat functionality"""
    return JsonResponse({'message': 'AI chat not implemented yet'})


def api_forwarder(request, path):
    """Placeholder for API forwarding functionality"""
    return JsonResponse({'message': 'API forwarder not implemented yet'})