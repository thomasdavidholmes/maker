This application exists to turn course topics into courseware. A freetext brief alongside any supporting files is passed to a set of agents whose goal is to generate an appropriate piece of courseware for the given topic. The level of the content can be ranked from Beginner (corresponding to a Lv. 3 or 4 in the UK apprenticeship system) to Expert (corresponding to Lv. 7 +) and can be selected from the web interface. The tool is designed to be launced from the command line and be locally hosted.

The interface will allow the user to select the type of course content they would like to be generated, with the set of options as follows:
* Jupyter notebook demonstration
* Jupyter notebook exercise
* Sample software project
* Microsoft word software exercise
* Powerpoint lecture.

The interface will also allow the user to enter the duration the content is designed for as a freetext field.

Once the input has been passed to the system, the draft content structure will be presented to the user for them to approve, or, if they do not believe it to be correct or sufficient, returned to the system to make further edits, before it it presented again. This will happen as many time as necessary.

The system should be agentic, and make use of the OpenAI Agent SDK, ideally trying to minimise model costs to the greates degree possible, while maintaining generated content quality. Preferably Python will be the main backend language, though you are at liberty to make decisions about leveraging other languages.

The goal of this project is to allow a trainer to generate informative, engaging, and exciting courseware in a variety of formats.