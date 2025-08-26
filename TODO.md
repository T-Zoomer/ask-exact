# TODO

* properly do the filter statements in the api. Think of a good way to make the filter statement parseble. First test if a basic filter statement works in the api because it doesnt so far. Maybe i need to string it or something? dont let claude go yolo do it myself claude it too dumb

* Make a function for each tool. 

* I should have a class / dict which holds are the user arguments and tool choices. This can be resent to LLM and hold the state / context for what the user wants. The job of the LLM is to parse chat messages to this object. This object includes, tool selection and arguments. 

* Later: Frontend, use htmx do make a nice chat interface. Use the templates from ask-accountant actually. 

* i want to be able to link multiple chat messages. Maybe also a better feature for later. 