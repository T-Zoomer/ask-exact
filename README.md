# Architecture

User intent forming proces
1. LLM gets told by user what the user wants
2. LLM determines tool (API call)
3. LLM gets send the argument spec for that tool and the user message. Then the LLM parses the LLM-facing arguments in UserIntent (start_date, end_date and the filters). 
4. Code parses the LLM-facing UserIntent arguments to API-facing arguments

So to build this i need to:

1. Finish the ExactToolbox
* FINISHED Get all the tool / API call specifications in a JSON. I was busy building a scraper for this: scrape_exact_api_specs.py 
* FINISHED Or just get some important ones but make them complete. 

2. 
* Then build a second LLM call where the LLM sees the user input, tool and the API spec. Then it parses input args.  
* Have to build the IntentParser anew. 

------


1. The user chats with the LLM and tells the LLM what it wants
2. The LLM knows what tools are available and what arguments per tool, given in context by ExactToolbox. 
3. The LLM parses the users intent to machine readable data, a class called UserIntent
4. The arguments in UserIntent that the LLM gives are not neccesarily the exact arguments needed by Exact API. Rather its the arguments that are the easyest and fault-proof for the LLM to give. 
---- up till here its not Exact Specifix, except for the ExactToolbox
5.  The UserIntent arguments are reformatted to the rigtht Exact API args. This is done by code. 
6. UserIntent is then executed, calling the tool with the reformatted arguments. This leads to a API call and chat reply. 



# Vision

An organisation exists out of people, but also out of the digital information that administers the running of the organisation. 

A major part of the work that is done by the organisational professional staff, is to manage and analyse this information. Often this work requires specialised roles, such as data analysts, financial controllers, clerks and BI developers. Their role is to analyse and present the information from the ERP programs into understandable chunks for management and organisational decision making. 

You need specialised people for this because the interface, the point where humans retrieve this data and make it exlpainable, is closed off, hard to work with, disjointed or technically difficult. We rebuild this interface with LLMs, making it approachable and easy to work with for management and decision makers directly. 