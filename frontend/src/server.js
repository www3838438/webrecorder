import express from 'express';
import React from 'react';
import { renderToString } from 'react-dom/server';
import compression from 'compression';
import http from 'http';
import proxy from 'http-proxy-middleware';
import path from 'path';
import { parse as parseUrl } from 'url';
import StaticRouter from 'react-router/StaticRouter';

import { ReduxAsyncConnect, loadOnServer } from 'redux-connect';
import { Provider } from 'react-redux';

import ApiClient from './helpers/ApiClient';
import { stripProtocol } from './helpers/utils';
import config from './config';
import createStore from './store/create';
import baseRoute from './baseRoute';
import BaseHtml from './helpers/BaseHtml';


const baseUrl = `http://${config.internalApiHost}:${config.internalApiPort}`;
const app = new express();
const server = new http.Server(app);
const bypassUrls = [
  '/api',
  '/_(reportissues|set_session|clear_session|client_ws|websockify|message)',
  '/_new*',
  '/websockify'
];

export default function (parameters) {
  // TODO: use nginx
  app.use(express.static(path.resolve(__dirname, '..')));

  // proxy api and other urls on localhost
  if (config.apiProxy) {
    // Proxy client API requets to server for now to avoid CORS
    app.use(bypassUrls, proxy({
      target: baseUrl,
      logLevel: 'debug',
      ws: true,
      headers: { 'X-Forwarded-Host': stripProtocol(config.appHost) }
    }));
  }

  if (!__DEVELOPMENT__) {
    app.use(compression());
  }

  // TODO: nginx, but for now intercept favicon.ico
  app.use('/favicon.ico', (req, res) => {
    res.status(404).send('Not Found');
  });

  app.use((req, res) => {
    const client = new ApiClient(req);
    const store = createStore(client);
    const url = req.originalUrl || req.url;
    const location = parseUrl(url);


    if (__DISABLE_SSR__) {
      res.send(`<!doctype html>\n
        ${renderToString(<BaseHtml assets={parameters.chunks()} store={store} />)}`);

      return;
    }

    loadOnServer({ store, location, routes: baseRoute }).then(() => {
      const context = {};

      const component = (
        <Provider store={store} key="provider">
          <StaticRouter location={location} context={context}>
            <ReduxAsyncConnect routes={baseRoute} />
          </StaticRouter>
        </Provider>
      );

      const outputHtml = renderToString(
        <BaseHtml
          assets={parameters && parameters.chunks()}
          component={component}
          store={store} />
      );

      res.status(context.status ? context.status : 200);

      global.navigator = { userAgent: req.headers['user-agent'] };

      res.send(`<!doctype html>\n ${outputHtml}`);
    });
  });

  if (config.port) {
    server.listen(config.port, (err) => {
      if (err) {
        console.error(err);
      }
      console.info('----\n==> ✅  %s is running, talking to API server on %s.', config.app.title, config.internalApiPort);
      console.info('==> 💻  Open %s in a browser to view the app.', config.appHost);
    });
  } else {
    console.error('==>     ERROR: No PORT environment variable has been specified');
  }

  process.on('unhandledRejection', (error) => {
    console.log('ERROR:', error);
  });

  return {
    server,
    app
  };
}
