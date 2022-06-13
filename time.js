function localize(time)
{
	var date=new Date(time);
	return document.write(date.toLocaleDateString() + " " + date.toLocaleTimeString());
}
