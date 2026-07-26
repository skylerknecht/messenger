# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] - 2026-07-26

- updated action to update the readme again
- updated action to update the readme
- add release setup
- Create release.yml
- update clients
- updated clients
- updated clients
- updated the docs
- typo
- Updated Typo
- Updated hyperlink for comms
- Created a new Messenger Comm Protocol doc
- rearranged some logicv
- updated clients
- added jinja2 to requirements
- updated relative pathing
- added __init__.py so that builder resources will be included
- updated pip to include messenger-builder
- updated clients
- removed the removal of clients as they clean themselves up
- added self to on_close call
- changed how on_closed is called
- updated submoudles
- Changes supported protocols for node js
- updated clients
- fixed minor bug with requirements and set_websocket returning empty lists, also added testing.md
- removed duplicate ports
- typo
- updated hyperlinks
- changed messenger-builder to be executable
- Updated the README
- added updated clients
- added status message for interact command when it could not find a matching messenger
- fixed typo
- removed build commands from help
- fixed bug with localport forwarder
- added and changed colors
- Added InitiateForwarderClientRep to remote port forward denies
- fixed bug where it showed the remote port forward identifier instead of messenger identifier.
- added pycryptodome to requirements
- remove messenger-builder from setup.py
- updated messenger-builder
- updated gitmodules
- added messenger-builder
- removed manual AES and added new build_python command
- removed size of 2GB for http based request
- moved status messages
- bumbped to 0.3.6
- fixed bug where websocket reconnection was not properly seralizing messages
- changed status messages for messengers
- bumped to 0.3.5
- updated status messages for messengers
- if debug is not zero then print the unhandled exception
- messenger will log unexpected excepctions to a log file
- messenger server will now queue messages to be sent even if the messenger is not alive
- refactored forwarders
- bumped to 0.3.4
- fixed an issue where positional arguments were being counted as keyword arguments
- bumped to 0.3.3
- fixed an issue where ForwarderClient was not starting the stream for remote port forwards
- bumped to 0.3.2
- fixed bug where top-ports was not accessible and clients not up to date
- minor help menu changes
- Added NodeJS hyperlink
- updated submodules and added update submodules command
- bumped to 0.3.1
- Fixed race condition where local port forwards would try sending data before they were connected
