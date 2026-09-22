
Use these notes to update the UI concepts, CLAUDE.md, and Genesis Markdown so moving forward code development matches my functionality goals of how i want this system to wokrk. Go though and extract the design concepts. 

My main goal With Genesis to create a system for users to do market research, backtest strategies, and apply computed based ideas to their trades. Gensis is based off a couple of systems I have seen in life. The first one is the JARVIS system from the movie iron man. IN my case Genesis is the name of the AI Orchestrator tht has full automany over the software. This system should be able to control the functionality of the system without users manual input. The system uses voice comamnds and LLM models to present the user what he or she is asking for with the help of subagents and MCP tools. Genesis shoudld be aflagship feature of the system but not the end all be all. The user should be able to interact with the system manually alongside Genesis. Essentially the orchestrator acts like a senior market anaylyst alongside the trader which is the Human. I can tell Gensis "Hey Gensis, tell me why Nvidia is down today?" Than geneis shoudl automatically open to teh tools asscoaited with figuring out thiazs answer. Tools might include. pulling up the chart, recent news, earnigns results, etc. Gensis would ecplain its insight ot the user. Although Gensis has automay to open tools, draw insights, and ocntrol the system, the users should be able to launch all the same tools as Genesis would than ask that question. Its key to know that Users are not always going to know the ticker of the stock so Gensis should be able to compute when a user says "Nvidia" the ticker is "NVDA". 

The functionality question is how do we build the UI to accomdiate this. I have taken inspirtion from different finacial terminals liek Bloomburg and Godell. I like how the workspace is almost like a open canvas with modular tools and cpmmands associated with said tool. Where i want my system to differ is data isnt just presented. Its computed, collected, and orchestrated by ai agents to allow the user to see deeper into the data. i am the head trader who talks the senior analyst (gensis orchestrator). Gensis than employes to 30 employees to draw conclusions, collect data, open tools, etc and present it to the trader. The feel the software should have is the User has an investment firm with an advisor and employees. The agents removed the need to do hours of research and Genesis present the information like a finaical advisor. It should make users feel like they now have 30 tarders, market analysts, and quant researhers on their team. 


Right now the UI is very clunky. You open it and have no clue whats going on and the only way to interact with is a voice agent that barely understands what i am talking about. it feels like i have thousads of lines of code but only 2-3 real  uses cases. The sotware opens with a bunch of information i didnt ask to see. I cant use any of the tools i spent a ton of time coding because they are all blocked behind the orchestor voice chat. i shoudld be greeted with an open canvas that allows me to start fresh. the system shoud act like an agentic terminal. i can type a command and the system shows me what tools i have access to. The user should act as the main commmander of the system not Genesis. Thea main ai voice should act as an afvisor, determine which commands to satisfy the users request, or employe the right agents to do the work. 

Examples.

"Hey Gensis, i am interested in WD Ganns Research. Do me a favor and do some deep research on his findings than save them in my research journal."

"Sure! I will start the research agents to search the web and gather information about his findings than save them in your journal"

1. Determines task at hand
2. Decides which tools and agents to employe to complete the task
3. Employes agents to do research
4. Checks sate of the task.
5. Saves findings into the journal
6. Presents the results back to user. 