const autoprefixer = require('autoprefixer');
const fs = require('fs');
const path = require('path');
const webpack = require('webpack');
const HardSourceWebpackPlugin = require('hard-source-webpack-plugin');

const assetsPath = path.resolve(__dirname, '../static/dist');

const webpackConfig = {
  devtool: 'cheap-module-source-map',
  context: path.resolve(__dirname, '..'),

  output: {
    path: assetsPath,
    publicPath: '/dist/',
    filename: '[name]-[hash].js',
    chunkFilename: '[name]-[chunkhash].js'
  },

  module: {
    rules: [
      {
        enforce: 'pre',
        test: /\.(js|jsx)?$/,
        exclude: /node_modules/,
        loader: 'eslint-loader',
        options: {
          quiet: true
        }
      },
      {
        test: /\.(js|jsx)?$/,
        exclude: /node_modules/,
        loader: 'babel-loader'
      },
      {
        test: /\.scss$/,
        use: [
          {
            loader: 'style-loader'
          },
          {
            loader: 'css-loader'
          },
          {
            loader: 'postcss-loader',
            options: {
              plugins: () => {
                return [
                  autoprefixer({
                    browsers: [
                      '>1%',
                      'last 4 versions',
                      'Firefox ESR',
                      'not ie < 9',
                    ]
                  })
                ];
              }
            }
          },
          'sass-loader'
        ]
      },
      {
        test: /\.css$/,
        use: [
          {
            loader: 'style-loader'
          },
          {
            loader: 'css-loader'
          }
        ]
      },
      {
        test: /\.woff(\?v=\d+\.\d+\.\d+)?$/,
        loader: 'url-loader',
        options: {
          limit: 10000,
          mimetype: 'application/font-woff'
        }
      },
      {
        test: /\.woff2(\?v=\d+\.\d+\.\d+)?$/,
        loader: 'url-loader',
        options: {
          limit: 10000,
          mimetype: 'application/font-woff'
        }
      },
      {
        test: /\.ttf(\?v=\d+\.\d+\.\d+)?$/,
        loader: 'url-loader',
        options: {
          limit: 10000,
          mimetype: 'application/octet-stream'
        }
      },
      {
        test: /\.eot(\?v=\d+\.\d+\.\d+)?$/,
        loader: 'file-loader'
      },
      {
        test: /\.svg(\?v=\d+\.\d+\.\d+)?$/,
        loader: 'url-loader',
        options: {
          limit: 10000,
          mimetype: 'image/svg+xml'
        }
      },
      {
        test: /\.(png|jpg|jpeg|gif)$/,
        loader: 'url-loader',
        options: {
          limit: 10240
        }
      }
    ]
  },

  resolve: {
    alias: {
      components: path.resolve(__dirname, '../src/components'),
      containers: path.resolve(__dirname, '../src/containers'),
      helpers: path.resolve(__dirname, '../src/helpers'),
      store: path.resolve(__dirname, '../src/store'),
      shared: path.resolve(__dirname, '../src/shared'),
      config: path.resolve(__dirname, '../src/config.js'),
      routes: path.resolve(__dirname, '../src/routes.js')
    },
    modules: [
      'node_modules',
      path.resolve(__dirname, '../src'),
    ],
    extensions: ['.json', '.js']
  },

  plugins: [
    new webpack.IgnorePlugin(/webpack-stats\.json$/),
    new HardSourceWebpackPlugin(),
    new webpack.EnvironmentPlugin([
      'NODE_ENV',
      'APP_HOST',
      'FRONTEND_PORT',
      'CONTENT_HOST'
    ])
  ]
};

export default webpackConfig;
