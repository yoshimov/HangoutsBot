import logging
import shlex
import asyncio
import re

import hangups

from Core.Commands import * # Makes sure that all commands in the Command directory are imported and registered.

from Core.Commands.Dispatcher import DispatcherSingleton
from Core.Util.UtilBot import is_user_blocked


class MessageHandler(object):
    """Handle Hangups conversation events"""

    def __init__(self, bot, bot_command='/'):
        self.bot = bot
        self.bot_command = bot_command
        DispatcherSingleton.run_init(self.bot)

    @staticmethod
    def word_in_text(word, text):
        """Return True if word is in text"""
        escaped = word.encode('unicode-escape').decode()
        if word != escaped:
            return word in text

        return True if re.search('\\b' + word + '\\b', text, re.IGNORECASE) else False

    @asyncio.coroutine
    def handle(self, event):
        if event.user.is_self or is_user_blocked(event.conv_id, event.user_id):
            return
        if event.conv_id not in self.bot.conv_settings:
            self.bot.conv_settings[event.conv_id] = {}
        try:
            muted = not self.bot.config['conversations'][event.conv_id]['autoreplies_enabled']
        except KeyError:
            muted = False
            from Core.Commands import DefaultCommands

            DefaultCommands.unmute(self.bot, event)

        event.text = event.text.replace('\xa0', ' ')

        """Handle conversation event"""
        if logging.root.level == logging.DEBUG:
            event.print_debug()

        if not event.user.is_self and event.text:
            if event.text.startswith(self.bot_command):
                # Run command
                if event.text[1] == '?':
                    event.text = "/help"
                yield from self.handle_command(event)
            else:
                # Forward messages
                yield from self.handle_forward(event)
                if not muted:
                    # Send automatic replies
                    yield from self.handle_autoreply(event)

    @asyncio.coroutine
    def handle_command(self, event):
        """Handle command messages"""
        # Test if command handling is enabled
        if not self.bot.get_config_suboption(event.conv_id, 'commands_enabled'):
            return

        # Parse message
        line_args = shlex.split(event.text, posix=False)
        i = 0
        while i < len(line_args):
            line_args[i] = line_args[i].strip()
            if line_args[i] == '' or line_args[i] == '':
                line_args.remove(line_args[i])
            else:
                i += 1


        # Test if command length is sufficient
        if len(line_args) < 1:
            self.bot.send_message(event.conv,
                                  '{}: Not a valid command.'.format(event.user.full_name))
            return

        # Test if user has permissions for running command

        has_permission = False
        commands_admin_list = self.bot.get_config_suboption(event.conv_id, 'commands_admin')
        if commands_admin_list and line_args[0].lower().replace(self.bot_command, '') in commands_admin_list:
            admins_list = self.bot.get_config_suboption(event.conv_id, 'admins')
            if admins_list is not None and event.user_id.chat_id in admins_list:
                has_permission = True
            else:
                has_permission = False

        if not has_permission:
            commands_conv_admin_list = self.bot.get_config_suboption(event.conv_id, 'commands_conversation_admin')
            if commands_conv_admin_list and line_args[0].lower().replace(self.bot_command,
                                                                         '') in commands_conv_admin_list:
                conv_admin = self.bot.get_config_suboption(event.conv_id, 'conversation_admin')
                if event.user_id.chat_id != conv_admin:
                    if not self.bot.dev:
                        self.bot.send_message(event.conv,
                                              "Sorry {}, I can't let you do that.".format(event.user.full_name))
                        return

        # Run command
        yield from DispatcherSingleton.run(self.bot, event, *line_args[0:])

    @asyncio.coroutine
    def handle_forward(self, event):
        # Test if message forwarding is enabled
        if not self.bot.get_config_suboption(event.conv_id, 'forwarding_enabled'):
            return

        forward_to_list = self.bot.get_config_suboption(event.conv_id, 'forward_to')
        if forward_to_list:
            for dst in forward_to_list:
                try:
                    conv = self.bot._conv_list.get(dst)
                except KeyError:
                    continue

                # Prepend forwarded message with name of sender
                link = 'https://plus.google.com/u/0/{}/about'.format(event.user_id.chat_id)
                segments = [hangups.ChatMessageSegment(event.user.full_name, hangups.SegmentType.LINK,
                                                       link_target=link, is_bold=True),
                            hangups.ChatMessageSegment(': ', is_bold=True)]
                # Copy original message segments
                segments.extend(event.conv_event.segments)
                # Append links to attachments (G+ photos) to forwarded message
                if event.conv_event.attachments:
                    segments.append(hangups.ChatMessageSegment('\n', hangups.SegmentType.LINE_BREAK))
                    segments.extend([hangups.ChatMessageSegment(link, hangups.SegmentType.LINK, link_target=link)
                                     for link in event.conv_event.attachments])
                self.bot.send_message_segments(conv, segments)

    @asyncio.coroutine
    def handle_autoreply(self, event):
        """Handle autoreplies to keywords in messages"""
        # Test if autoreplies are enabled
        if not self.bot.get_config_suboption(event.conv_id, 'autoreplies_enabled'):
            return

        autoreplies_list = self.bot.get_config_suboption(event.conv_id, 'autoreplies')
        if autoreplies_list:
            for kwds, sentence in autoreplies_list:
                for kw in kwds:
                    if self.word_in_text(kw, event.text) or kw == "*":
                        if sentence[0] == self.bot_command:
                            event.text = sentence.format(event.text)
                            yield from self.handle_command(event)
                        else:
                            self.bot.send_message(event.conv, sentence)
                        break
