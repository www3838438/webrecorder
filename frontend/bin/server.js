#!/usr/bin/env node
import { server } from 'universal-webpack';
import settings from '../webpack/universal-webpack-settings.json';
import wpConfig from '../webpack/webpack.config';


/**
 * Define isomorphic constants.
 */
global.__CLIENT__ = false;
global.__SERVER__ = true;
global.__DISABLE_SSR__ = process.env.DISABLE_SSR ? process.env.DISABLE_SSR === 'true' : false;
global.__PLAYER__ = false;
global.__DEVELOPMENT__ = process.env.NODE_ENV !== 'production';

server(wpConfig, settings);
