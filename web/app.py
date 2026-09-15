from flask import Flask, jsonify, render_template, request, redirect, url_for, session
import os, hmac
# existing file content preserved; only require_login behavior is changed below
