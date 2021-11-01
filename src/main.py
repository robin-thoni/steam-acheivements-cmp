#! /usr/bin/env python3

import sys

import argparse
import typing
from enum import Enum

import jinja2
import pydantic
import yaml
import requests
from colored import fg, bg, attr
from tabulate import tabulate


def to_yaml(value):
    value_str = yaml.safe_dump(value, default_style='"', default_flow_style=True)
    return value_str[:-1] if value_str and value_str[-1] == '\n' else value_str


class ConfigBase(pydantic.BaseModel):
    pass


class ConfigRoot(ConfigBase):
    steam_api_key: str = pydantic.Field()
    language: str = pydantic.Field()
    appid: str = pydantic.Field()
    steamids: typing.List[str] = pydantic.Field()


class OptionsFilter(Enum):
    ALL = 'all'
    OK = 'ok'
    PART = 'part'
    NONE = 'none'


class Options(pydantic.BaseModel):
    config_path: str = pydantic.Field(alias='config')
    # filter_status: OptionsFilter = pydantic.Field(default=OptionsFilter.ALL)
    filter: str = pydantic.Field(default='True')


def my_all(l, fn):
    for i in l:
        if not fn(i):
            return False
    return True


def my_any(l, fn):
    for i in l:
        if fn(i):
            return True
    return False


def has_achievement(p):
    return p['achieved'] == 1


def main(argv):
    default_options = Options(**{
        'config': './config.yml',
        'filter': 'True'
    })

    parser = argparse.ArgumentParser(description='Some awesome project')
    parser.add_argument('-c', '--config', type=str, default=default_options.config_path, help='Path to config file')
    parser.add_argument('-f', '--filter', type=str, default=default_options.filter, help='Path to config file')
    args = parser.parse_args(argv[1:])

    options = Options(**vars(args))

    with open(options.config_path, 'r') as f:
        config_template = f.read()

    jinja_env = jinja2.Environment(
        loader=jinja2.PrefixLoader({
            'config': jinja2.DictLoader({
                'config.yml': config_template
            }),
            'config.d': jinja2.FileSystemLoader('{}.d'.format(options.config_path))
        }),
        extensions=["jinja2.ext.do"]
    )
    jinja_env.filters['yaml'] = to_yaml

    template = jinja_env.get_template('config/config.yml')
    config_yml = template.render(options=options)
    config_dict = yaml.safe_load(config_yml)
    config = ConfigRoot(**config_dict)

    achievements_per_player = {}
    session = requests.session()

    r = session.get('http://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/', params={
            'key': config.steam_api_key,
            'steamids': ','.join(config.steamids),
    })
    r.raise_for_status()
    data = r.json()
    players = {p['steamid']: p for p in data['response']['players']}

    for steamid in config.steamids:
        r = session.get('https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v1/', params={
            'key': config.steam_api_key,
            'steamid': steamid,
            'appid': config.appid,
            'l': config.language
        })
        r.raise_for_status()
        achievements_per_player[steamid] = r.json()['playerstats']['achievements']

    achievements = {}
    for steamid in achievements_per_player:
        for achievement_player in achievements_per_player[steamid]:
            if achievement_player['apiname'] not in achievements:
                achievements[achievement_player['apiname']] = {
                    'apiname': achievement_player['apiname'],
                    'name': achievement_player['name'],
                    'description': achievement_player['description'],
                    'players': []
                }
            achievements[achievement_player['apiname']]['players'].append({
                'steamid': steamid,
                'achieved': achievement_player['achieved'],
                'unlocktime': achievement_player['unlocktime'],
            })

    status_str = {
        OptionsFilter.OK: '{} OK {}'.format(fg('green'), attr('reset')),
        OptionsFilter.PART: '{}PART{}'.format(fg('orange_1'), attr('reset')),
        OptionsFilter.NONE: '{}NONE{}'.format(fg('red'), attr('reset')),
    }

    headers = ['Status', 'Name', 'Description'] + [players[steamid]['personaname'] for steamid in config.steamids]
    table_data = []
    for achievement_id in achievements:
        achievement = achievements[achievement_id]
        if my_all(achievement['players'], has_achievement):
            status = OptionsFilter.OK
        elif my_any(achievement['players'], has_achievement):
            status = OptionsFilter.PART
        else:
            status = OptionsFilter.NONE
        if eval(options.filter, {
            'ok': OptionsFilter.OK,
            'part': OptionsFilter.PART,
            'none': OptionsFilter.NONE,
            'status': status,

            'name': achievement['name'],
            'desc': achievement['description'],
            'description': achievement['description'],
        }):
            table_data.append([status_str[status], achievement['name'], achievement['description']] + [status_str[OptionsFilter.OK] if achievement['players'][i]['achieved'] == 1 else status_str[OptionsFilter.NONE] for i in range(len(config.steamids))])

    print(tabulate(table_data, headers=headers, tablefmt='simple'))

    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
